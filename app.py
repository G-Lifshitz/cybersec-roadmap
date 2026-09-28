import os
import secrets
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, session, g
from dotenv import load_dotenv

load_dotenv()

from db import init_db
import models.roadmap as roadmap_model
import models.progress as progress_model
import models.users as users_model
import models.ratelimit as ratelimit
from services.youtube import RecommendationService

app = Flask(__name__)
# The secret key signs the session cookie that says who is logged in. With no
# SECRET_KEY set we generate a random one rather than fall back to a known
# string: anyone who knew a hard-coded default could forge a login cookie.
# Trade-off: without SECRET_KEY, restarting the app logs everyone out.
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,   # page JavaScript can't read the cookie
    SESSION_COOKIE_SAMESITE="Lax",  # cookie isn't sent on cross-site POSTs (basic CSRF protection)
    MAX_CONTENT_LENGTH=64 * 1024,   # reject request bodies over 64 KB before reading them (413)
)

# ── Rate-limit policy ──────────────────────────────────────────────────────
# (limit, window in seconds). Failed logins are counted two ways:
#  - per username+IP: stops guessing one account's password from one machine,
#    without letting a stranger lock the real owner out from somewhere else;
#  - per IP: stops one machine spraying guesses across many usernames.
LOGIN_FAILS_PER_ACCOUNT = (5, 15 * 60)
LOGIN_FAILS_PER_IP = (20, 15 * 60)
REGISTRATIONS_PER_IP = (5, 60 * 60)

# Server-side field caps. The HTML maxlength attributes are only a hint; a
# script can POST anything, so the real limit has to be enforced here.
MAX_LEN = {"title": 200, "url": 500, "skill_tags": 200, "notes": 2000, "platform": 50}

PORT = int(os.environ.get("PORT", 5000))

ITEM_TYPES = ["course", "cert", "lab", "book", "project"]
PLATFORMS = ["HTB", "THM", "YouTube", "Coursera", "OffSec", "TCM", "Other"]
DIFFICULTIES = ["beginner", "intermediate", "advanced"]
STATUSES = ["not_started", "in_progress", "completed"]
FELT_DIFFICULTIES = ["easy", "fair", "hard", "brutal"]

# Single Facade instance — all routes call through it
_rec = RecommendationService()


# ── Auth ───────────────────────────────────────────────────────────────────

@app.before_request
def load_current_user():
    """Look up the logged-in user once per request and keep it on g."""
    user_id = session.get("user_id")
    g.user = users_model.get_by_id(user_id) if user_id else None


def login_required(view):
    """Decorator: send anonymous visitors to the login page, then back here."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def _safe_next(target):
    """Only follow ?next= to paths on this site, never to another domain."""
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("index")


def _client_ip():
    # remote_addr is the direct peer. X-Forwarded-For is deliberately ignored:
    # clients can set it to anything, so trusting it would let an attacker
    # pick a new "IP" per request. Behind a real proxy (Assignment 2) this
    # needs ProxyFix configured with the known number of proxies.
    return request.remote_addr or "unknown"


def _too_many(template, message, kind, key, window, **ctx):
    """Render the form again with HTTP 429 and a Retry-After header."""
    wait = ratelimit.retry_after(kind, key, window)
    flash(f"{message} Try again in {max(1, wait // 60)} min.")
    resp = app.make_response((render_template(template, **ctx), 429))
    resp.headers["Retry-After"] = str(wait)
    return resp


def _start_session(user):
    session.clear()  # drop anything from before login (session fixation)
    session["user_id"] = user["id"]


@app.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("index"))
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        ip = _client_ip()
        limit, window = REGISTRATIONS_PER_IP
        if ratelimit.is_limited("register", ip, limit, window):
            return _too_many("register.html", "Too many sign-up attempts.",
                             "register", ip, window, username=username)
        ratelimit.record("register", ip)
        if password != request.form.get("confirm", ""):
            flash("Passwords don't match.")
            return render_template("register.html", username=username)
        try:
            user_id = users_model.create_user(username, password)
        except users_model.RegistrationError as e:
            flash(str(e))
            return render_template("register.html", username=username)
        _start_session({"id": user_id})
        flash("Account created. Add the first thing you want to learn.")
        return redirect(url_for("index"))
    return render_template("register.html", username="")


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("index"))
    if request.method == "POST":
        username = request.form.get("username", "")
        ip = _client_ip()
        account_key = f"{username.strip().lower()}|{ip}"
        acct_limit, acct_window = LOGIN_FAILS_PER_ACCOUNT
        ip_limit, ip_window = LOGIN_FAILS_PER_IP

        # Check the limits BEFORE checking the password: once locked, even the
        # right password is refused, otherwise the lockout leaks which guess worked.
        if ratelimit.is_limited("login_fail", account_key, acct_limit, acct_window):
            return _too_many("login.html", "Too many failed attempts for this account.",
                             "login_fail", account_key, acct_window, username=username)
        if ratelimit.is_limited("login_fail_ip", ip, ip_limit, ip_window):
            return _too_many("login.html", "Too many failed attempts from your network.",
                             "login_fail_ip", ip, ip_window, username=username)

        user = users_model.authenticate(username, request.form.get("password", ""))
        if user is None:
            ratelimit.record("login_fail", account_key)
            ratelimit.record("login_fail_ip", ip)
            flash("Wrong username or password.")
            return render_template("login.html", username=username)

        ratelimit.clear("login_fail", account_key)  # a success resets that account's count
        _start_session(user)
        return redirect(_safe_next(request.args.get("next")))
    return render_template("login.html", username="")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Logged out.")
    return redirect(url_for("login"))


# ── Dashboard ──────────────────────────────────────────────────────────────

@app.route("/")
@login_required
def index():
    uid = g.user["id"]
    filters = {
        "status": request.args.get("status") or None,
        "skill": request.args.get("skill") or None,
        "search": request.args.get("q", "").strip() or None,
        "type_": request.args.get("type") or None,
    }
    items = roadmap_model.get_all(uid, **filters)
    skill_summary = roadmap_model.get_skill_summary(uid)
    weak = progress_model.weak_skills(uid)
    total_mins = progress_model.total_time_spent(uid)

    # Attach latest completion % to each item
    enriched = []
    for item in items:
        enriched.append({
            **dict(item),
            "completion": progress_model.latest_completion(item["id"]),
        })

    return render_template(
        "index.html",
        items=enriched,
        skill_summary=skill_summary,
        weak_skills=weak,
        total_hours=round(total_mins / 60, 1),
        counts=roadmap_model.get_status_counts(uid),
        statuses=STATUSES,
        item_types=ITEM_TYPES,
        all_tags=roadmap_model.get_all_tags(uid),
        filters=filters,
        filtering=any(filters.values()),
    )


# ── Roadmap items ──────────────────────────────────────────────────────────

def _item_form_data():
    """Read and clean the add/edit form. Shared by both routes so they can't drift apart."""
    try:
        priority = max(1, min(5, int(request.form.get("priority", 3))))
    except ValueError:
        priority = 3
    field = lambda name, default="": request.form.get(name, default).strip()[:MAX_LEN[name]]
    item_type = request.form.get("type", "course")
    difficulty = request.form.get("difficulty", "beginner")
    return {
        "title": field("title"),
        # Only accept values from the fixed option lists; anything else falls back
        "type": item_type if item_type in ITEM_TYPES else "course",
        "platform": field("platform"),
        "url": field("url"),
        "skill_tags": field("skill_tags"),
        "difficulty": difficulty if difficulty in DIFFICULTIES else "beginner",
        "priority": priority,
    }


def _form_choices():
    return dict(item_types=ITEM_TYPES, platforms=PLATFORMS, difficulties=DIFFICULTIES)


@app.route("/add", methods=["GET", "POST"])
@login_required
def add_item():
    if request.method == "POST":
        data = _item_form_data()
        if not data["title"]:
            flash("Title is required.")
            return render_template("add.html", item=data, **_form_choices())

        roadmap_model.create(
            user_id=g.user["id"],
            title=data["title"],
            type_=data["type"],
            platform=data["platform"],
            url=data["url"],
            skill_tags=data["skill_tags"],
            difficulty=data["difficulty"],
            priority=data["priority"],
        )
        flash(f'"{data["title"]}" added to your roadmap.')
        return redirect(url_for("index"))

    return render_template("add.html", item={}, **_form_choices())


@app.route("/item/<int:item_id>/edit", methods=["GET", "POST"])
@login_required
def edit_item(item_id):
    item = roadmap_model.get_by_id(item_id, g.user["id"])
    if not item:
        flash("Item not found.")
        return redirect(url_for("index"))

    if request.method == "POST":
        data = _item_form_data()
        if not data["title"]:
            flash("Title is required.")
            return render_template("edit.html", item={**data, "id": item_id}, **_form_choices())
        roadmap_model.update(item_id, g.user["id"], **data)
        flash("Changes saved.")
        return redirect(url_for("item_detail", item_id=item_id))

    return render_template("edit.html", item=dict(item), **_form_choices())


@app.route("/item/<int:item_id>")
@login_required
def item_detail(item_id):
    # get_by_id is owner-scoped, so after this check the log queries below
    # (which only take item_id) are guaranteed to be on this user's item.
    item = roadmap_model.get_by_id(item_id, g.user["id"])
    if not item:
        flash("Item not found.")
        return redirect(url_for("index"))

    logs = progress_model.get_logs_for_item(item_id)
    completion = progress_model.latest_completion(item_id)

    # YouTube recommendations via the RecommendationService facade
    tags = [t.strip() for t in (item["skill_tags"] or "").split(",") if t.strip()]
    videos = _rec.for_item(tags)

    return render_template(
        "item.html",
        item=dict(item),
        logs=logs,
        completion=completion,
        videos=videos,
        felt_difficulties=FELT_DIFFICULTIES,
    )


@app.route("/item/<int:item_id>/log", methods=["POST"])
@login_required
def log_progress(item_id):
    item = roadmap_model.get_by_id(item_id, g.user["id"])
    if not item:
        flash("Item not found.")
        return redirect(url_for("index"))

    try:
        pct = max(0, min(100, int(request.form.get("completion_pct", 0))))
        mins = max(0, min(24 * 60, int(request.form.get("time_spent_mins", 0) or 0)))
    except ValueError:
        flash("Completion and time must be numbers.")
        return redirect(url_for("item_detail", item_id=item_id))
    felt = request.form.get("felt_difficulty")
    progress_model.add_log(
        item_id=item_id,
        completion_pct=pct,
        felt_difficulty=felt if felt in FELT_DIFFICULTIES else None,
        notes=request.form.get("notes", "").strip()[:MAX_LEN["notes"]],
        time_spent_mins=mins,
    )
    flash("Progress logged.")
    return redirect(url_for("item_detail", item_id=item_id))


@app.route("/item/<int:item_id>/delete", methods=["POST"])
@login_required
def delete_item(item_id):
    if roadmap_model.delete(item_id, g.user["id"]):
        flash("Item removed.")
    else:
        flash("Item not found.")
    return redirect(url_for("index"))


# ── Recommendations ────────────────────────────────────────────────────────

@app.route("/recommendations")
@login_required
def recommendations():
    weak = progress_model.weak_skills(g.user["id"])
    videos, subs = _rec.for_weak_skills(weak)
    return render_template(
        "recommendations.html",
        weak_skills=weak,
        videos=videos,
        subscriptions=subs,
    )


# ── Entry point ────────────────────────────────────────────────────────────

@app.errorhandler(413)
def too_large(_):
    return "Request too large.", 413


init_db()
ratelimit.prune(older_than=24 * 60 * 60)  # drop day-old rate-limit rows at startup

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=os.environ.get("FLASK_DEBUG", "0") == "1")
