import os
import secrets
from datetime import date, datetime, timezone
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, session, g, abort
from dotenv import load_dotenv

load_dotenv()

from db import init_db
import models.roadmap as roadmap_model
import models.progress as progress_model
import models.users as users_model
import models.ratelimit as ratelimit
import models.assessment as assessment_model
from services.youtube import RecommendationService
import services.stats as stats_service
import services.export as export_service
from services.assessment import LEVEL_LABELS, LEVELS, AssessmentError, Questionnaire
from services.question_bank import FIELDS as QUESTION_BANK
from services.timelines import TimelinePlanner
from services.timeline_catalog import TRACKS as TIMELINE_CATALOGUE
from ui.icons import icon
from ui.navigation import links_for

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
# The question bank is injected here, so the scoring code never imports the data itself
_quiz = Questionnaire(QUESTION_BANK)
# Same idea for the timeline: the phases are data, injected into the planner here
_planner = TimelinePlanner(TIMELINE_CATALOGUE)
LEVEL_CHOICES = [(level, LEVEL_LABELS[level]) for level in LEVELS]

# Template helpers: {{ icon('book') }} and {% for t in item.skill_tags | tags %}
app.add_template_global(icon)
app.add_template_filter(roadmap_model.split_tags, "tags")
app.add_template_filter(stats_service.duration, "duration")   # 90 -> "1h 30m"


@app.context_processor
def inject_navigation():
    return {"nav_links": links_for(g.get("user"))}


# ── Auth ───────────────────────────────────────────────────────────────────

@app.before_request
def load_current_user():
    """Look up the logged-in user once per request and keep it on g."""
    user_id = session.get("user_id")
    g.user = users_model.get_by_id(user_id) if user_id else None
    # A password change bumps session_epoch. A cookie issued before that
    # (e.g. on another device, or a stolen one) no longer matches -> logged out.
    if g.user and session.get("epoch") != g.user["session_epoch"]:
        session.clear()
        g.user = None


def login_required(view):
    """Decorator: send anonymous visitors to the login page, then back here."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    """Decorator: admins only. Everyone else gets a 404, as if the page didn't exist."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None or not g.user["is_admin"]:
            abort(404)
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


def _start_session(user_id):
    session.clear()  # drop anything from before login (session fixation)
    session["user_id"] = user_id
    session["epoch"] = users_model.get_by_id(user_id)["session_epoch"]


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
        _start_session(user_id)
        flash("Account created. Take the short assessment to find your level.")
        return redirect(url_for("assessment"))
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
            # Only real accounts get a history entry; the message stays identical either way.
            target_id = users_model.get_id_by_username(username)
            if target_id:
                users_model.record_login(target_id, False, ip)
            flash("Wrong username or password.")
            return render_template("login.html", username=username)

        ratelimit.clear("login_fail", account_key)  # a success resets that account's count
        failed = users_model.failed_since_last_login(user["id"])
        users_model.record_login(user["id"], True, ip)
        _start_session(user["id"])
        if failed:
            flash(f"Heads up: {failed} failed login attempt{'s' if failed != 1 else ''} "
                  "on your account since you last logged in. Check Settings if that wasn't you.")
        return redirect(_safe_next(request.args.get("next")))
    return render_template("login.html", username="")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Logged out.")
    return redirect(url_for("login"))


# ── Dashboard ──────────────────────────────────────────────────────────────

@app.route("/progress")
@login_required
def progress():
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
        "progress.html",
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


# ── Timeline (home page) ───────────────────────────────────────────────────

def _current_path(user):
    """(field, level) the timeline is built for: the saved choice, else the latest assessment, else None."""
    if _planner.is_valid(user["path_field"], user["path_level"]):
        return user["path_field"], user["path_level"]
    latest = assessment_model.history(user["id"], limit=1)
    if latest and _planner.is_valid(latest[0]["field"], latest[0]["level"]):
        return latest[0]["field"], latest[0]["level"]
    return None


@app.route("/")
@login_required
def index():
    path = _current_path(g.user)
    if path is None:
        return render_template("path.html", fields=_planner.fields(), levels=LEVEL_CHOICES, current=None)
    field, level = path
    timeline = _planner.plan(field, level, roadmap_model.get_all(g.user["id"]), date.today())
    return render_template("timeline.html", timeline=timeline, levels=LEVEL_CHOICES, fields=_planner.fields())


@app.route("/path", methods=["GET", "POST"])
@login_required
def choose_path():
    if request.method == "POST":
        field, level = request.form.get("field", ""), request.form.get("level", "")
        if not _planner.is_valid(field, level):
            flash("Pick a field and a level from the list.")
            return redirect(url_for("choose_path"))
        users_model.set_path(g.user["id"], field, level)
        return redirect(url_for("index"))
    return render_template("path.html", fields=_planner.fields(), levels=LEVEL_CHOICES,
                           current=_current_path(g.user))


@app.route("/timeline/phase/<int:number>/add", methods=["POST"])
@login_required
def add_phase(number):
    path = _current_path(g.user)
    if path is None:
        return redirect(url_for("index"))
    try:
        items = _planner.items_for_phase(path[0], number)
    except IndexError:
        abort(404)
    added = roadmap_model.create_many(g.user["id"], items)
    if added:
        flash(f"Added {added} item{'s' if added != 1 else ''} to your roadmap.")
    else:
        flash("Everything in this phase is already on your roadmap.")
    return redirect(url_for("index"))


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
        return redirect(url_for("progress"))

    return render_template("add.html", item={}, **_form_choices())


@app.route("/item/<int:item_id>/edit", methods=["GET", "POST"])
@login_required
def edit_item(item_id):
    item = roadmap_model.get_by_id(item_id, g.user["id"])
    if not item:
        flash("Item not found.")
        return redirect(url_for("progress"))

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
        return redirect(url_for("progress"))

    logs = progress_model.get_logs_for_item(item_id)
    completion = progress_model.latest_completion(item_id)

    # YouTube recommendations via the RecommendationService facade
    videos = _rec.for_item(roadmap_model.split_tags(item["skill_tags"]))

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
        return redirect(url_for("progress"))

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
    return redirect(url_for("progress"))


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


# ── Stats ──────────────────────────────────────────────────────────────────

@app.route("/stats")
@login_required
def stats():
    # Logs are stamped in UTC, so "today" is the UTC date too.
    today = datetime.now(timezone.utc).date()
    year, month = stats_service.parse_month(request.args.get("month"), today)
    entries = stats_service.to_entries(progress_model.time_entries(g.user["id"]))
    return render_template("stats.html", report=stats_service.build_report(entries, today, year, month))


# ── Career assessment ──────────────────────────────────────────────────────

@app.route("/assessment")
@login_required
def assessment():
    return render_template(
        "assessment.html",
        fields=_quiz.fields(),
        names=_quiz.names(),
        history=assessment_model.history(g.user["id"]),
    )


@app.route("/assessment/<field>", methods=["GET", "POST"])
@login_required
def take_assessment(field):
    questions = _quiz.field(field)
    if questions is None:
        abort(404)
    if request.method == "POST":
        try:
            result = _quiz.score(field, request.form)
        except AssessmentError as e:
            flash(str(e))
            return render_template("quiz.html", field_key=field, field=questions, chosen=request.form)
        attempt_id = assessment_model.save(
            g.user["id"], field, result.answers, result.score, result.max_score, result.level
        )
        if _planner.is_valid(field, result.level):
            users_model.set_path(g.user["id"], field, result.level)  # the timeline follows the latest result
        return redirect(url_for("assessment_result", attempt_id=attempt_id))
    return render_template("quiz.html", field_key=field, field=questions, chosen={})


@app.route("/assessment/result/<int:attempt_id>")
@login_required
def assessment_result(attempt_id):
    attempt = assessment_model.get(attempt_id, g.user["id"])  # owner-scoped
    if attempt is None:
        flash("Result not found.")
        return redirect(url_for("assessment"))
    try:
        # Recomputed from the stored answers, so strengths and gaps aren't duplicated in the DB
        result = _quiz.score(attempt["field"], attempt["answers"])
    except AssessmentError:
        flash("That result was taken on an older version of the questions. Please retake it.")
        return redirect(url_for("assessment"))
    return render_template("result.html", result=result, taken_at=attempt["taken_at"])


# ── Settings ───────────────────────────────────────────────────────────────

def _settings_page():
    return render_template("settings.html", logins=users_model.recent_logins(g.user["id"]))


def _settings_guard():
    """Rate-limit wrong 'current password' entries, so a hijacked session can't brute-force it."""
    key = f"settings|{g.user['id']}"
    limit, window = LOGIN_FAILS_PER_ACCOUNT
    if ratelimit.is_limited("login_fail", key, limit, window):
        return key, _too_many("settings.html", "Too many wrong password attempts.",
                              "login_fail", key, window,
                              logins=users_model.recent_logins(g.user["id"]))
    return key, None


@app.route("/settings")
@login_required
def settings():
    return _settings_page()


@app.route("/settings/password", methods=["POST"])
@login_required
def change_password():
    key, blocked = _settings_guard()
    if blocked:
        return blocked
    new = request.form.get("new_password", "")
    if new != request.form.get("confirm", ""):
        flash("New passwords don't match.")
        return _settings_page()
    try:
        epoch = users_model.change_password(g.user["id"], request.form.get("current_password", ""), new)
    except users_model.AccountError as e:
        if "Current password" in str(e):
            ratelimit.record("login_fail", key)
        flash(str(e))
        return _settings_page()
    session["epoch"] = epoch  # keep THIS session; every other one is now invalid
    flash("Password changed. You've been logged out on every other device.")
    return redirect(url_for("settings"))


@app.route("/settings/delete", methods=["POST"])
@login_required
def delete_account():
    key, blocked = _settings_guard()
    if blocked:
        return blocked
    try:
        users_model.delete_account(g.user["id"], request.form.get("password", ""))
    except users_model.AccountError as e:
        if "Password is wrong" in str(e):
            ratelimit.record("login_fail", key)
        flash(str(e))
        return _settings_page()
    session.clear()
    flash("Your account and all your data have been deleted.")
    return redirect(url_for("login"))


@app.route("/settings/export/<name>")
@login_required
def export_data(name):
    """Download everything stored about the logged-in user (GDPR access / portability)."""
    if name not in export_service.FORMATS:
        abort(404)
    build, content_type = export_service.FORMATS[name]
    response = app.make_response(build(export_service.collect(g.user["id"])))
    response.headers["Content-Type"] = f"{content_type}; charset=utf-8"
    response.headers["Content-Disposition"] = f'attachment; filename="cyberroadmap-{date.today()}-{name}"'
    response.headers["Cache-Control"] = "no-store"  # personal data: don't keep it in browser or proxy caches
    return response


# ── Admin ──────────────────────────────────────────────────────────────────

@app.route("/admin")
@admin_required
def admin():
    users = users_model.list_with_stats()
    return render_template(
        "admin.html",
        users=users,
        totals={
            "users": len(users),
            "items": sum(u["items"] for u in users),
            "logs": sum(u["logs"] for u in users),
            "hours": round(sum(u["minutes"] for u in users) / 60, 1),
        },
        account_locks=ratelimit.active_lockouts("login_fail", *LOGIN_FAILS_PER_ACCOUNT),
        ip_locks=ratelimit.active_lockouts("login_fail_ip", *LOGIN_FAILS_PER_IP),
    )


@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def admin_delete_user(user_id):
    if user_id == g.user["id"]:
        flash("You can't delete your own admin account.")
    elif users_model.delete_user(user_id):
        flash("User and all their data deleted.")
    else:
        flash("User not found.")
    return redirect(url_for("admin"))


@app.route("/admin/lockouts/clear", methods=["POST"])
@admin_required
def admin_clear_lockouts():
    n = ratelimit.clear_kinds("login_fail", "login_fail_ip")
    flash(f"Cleared {n} failed-login records. All lockouts lifted.")
    return redirect(url_for("admin"))


@app.errorhandler(413)
def too_large(_):
    return "Request too large.", 413


init_db()
# Admin account comes from the environment, never from source code.
# Leave ADMIN_USERNAME / ADMIN_PASSWORD unset and no admin is created.
users_model.ensure_admin(os.environ.get("ADMIN_USERNAME"), os.environ.get("ADMIN_PASSWORD"))
ratelimit.prune(older_than=24 * 60 * 60)  # drop day-old rate-limit rows at startup

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=os.environ.get("FLASK_DEBUG", "0") == "1")
