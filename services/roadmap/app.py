"""Roadmap service: accounts, roadmap items, the career timeline and the assessment.

JSON API only; the UI is static files in ui/ (A2 §2). Endpoints are listed in
openapi.yaml. Every item route is owner-scoped through the bearer token.
"""
from datetime import date
from functools import wraps

from flask import Flask, abort, g, jsonify, request

import auth
import models.assessment as assessment_model
import models.ratelimit as ratelimit
import models.roadmap as roadmap_model
import models.users as users_model
import web
from domain.assessment import LEVEL_LABELS, LEVELS, AssessmentError, Questionnaire
from domain.question_bank import FIELDS as QUESTION_BANK
from domain.timeline_catalog import TRACKS as TIMELINE_CATALOGUE
from domain.timelines import TimelinePlanner
from progress_client import ProgressClient, ProgressUnavailable
from serialize import jsonable

# (limit, window in seconds). Failed logins are counted per username+IP (stops
# guessing one account's password without letting a stranger lock the owner
# out from elsewhere) and per IP (stops spraying guesses across usernames).
LOGIN_FAILS_PER_ACCOUNT = (5, 15 * 60)
LOGIN_FAILS_PER_IP = (20, 15 * 60)
REGISTRATIONS_PER_IP = (5, 60 * 60)

MAX_LEN = {"title": 200, "url": 500, "skill_tags": 200, "platform": 50}
ITEM_TYPES = ["course", "cert", "lab", "book", "project"]
PLATFORMS = ["HTB", "THM", "YouTube", "Coursera", "OffSec", "TCM", "GitHub", "Other"]
DIFFICULTIES = ["beginner", "intermediate", "advanced"]

_quiz = Questionnaire(QUESTION_BANK)
_planner = TimelinePlanner(TIMELINE_CATALOGUE)


def create_app(progress=None):
    app = Flask(__name__)
    web.setup(app, "roadmap")
    progress = progress or ProgressClient()

    # ── Auth helpers ────────────────────────────────────────────────────────

    def login_required(view):
        """Resolve the bearer token to g.user, or 401.

        Also checks the token's epoch against the database, so tokens issued
        before a password change are rejected here.
        """
        @wraps(view)
        def wrapped(*args, **kwargs):
            token = auth.bearer(request.headers)
            if not token:
                abort(401, "Log in first.")
            try:
                user_id, epoch = auth.verify(token)
            except auth.InvalidToken:
                abort(401, "Your session has expired. Log in again.")
            user = users_model.get_by_id(user_id)
            if user is None or user["session_epoch"] != epoch:
                abort(401, "Your session has expired. Log in again.")
            g.user, g.token = user, token
            return view(*args, **kwargs)
        return wrapped

    def body():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            abort(400, "Expected a JSON object.")
        return data

    def client_ip():
        # remote_addr is the direct peer; on Azure ProxyFix (TRUST_PROXY=1)
        # replaces it with the one X-Forwarded-For hop Container Apps adds.
        return request.remote_addr or "unknown"

    def too_many(message, kind, key, window):
        wait = ratelimit.retry_after(kind, key, window)
        resp = jsonify(error="too_many_requests", message=f"{message} Try again in {max(1, wait // 60)} min.")
        resp.status_code = 429
        resp.headers["Retry-After"] = str(wait)
        return resp

    def public_user(user):
        return {"id": user["id"], "username": user["username"], "is_admin": bool(user["is_admin"]),
                "path_field": user["path_field"], "path_level": user["path_level"]}

    def session_for(user, **extra):
        return jsonify(token=auth.issue(user["id"], user["session_epoch"]), user=public_user(user), **extra)

    # ── Accounts ────────────────────────────────────────────────────────────

    @app.post("/auth/register")
    def register():
        data = body()
        ip = client_ip()
        limit, window = REGISTRATIONS_PER_IP
        if ratelimit.is_limited("register", ip, limit, window):
            return too_many("Too many sign-up attempts.", "register", ip, window)
        ratelimit.record("register", ip)
        try:
            user_id = users_model.create_user(data.get("username"), data.get("password"))
        except users_model.RegistrationError as e:
            abort(400, str(e))
        resp = session_for(users_model.get_by_id(user_id))
        resp.status_code = 201
        return resp

    @app.post("/auth/login")
    def login():
        data = body()
        username = str(data.get("username") or "")
        ip = client_ip()
        account_key = f"{username.strip().lower()}|{ip}"
        acct_limit, acct_window = LOGIN_FAILS_PER_ACCOUNT
        ip_limit, ip_window = LOGIN_FAILS_PER_IP
        # Limits are checked BEFORE the password: once locked, even the right
        # password is refused, otherwise the lockout leaks which guess worked.
        if ratelimit.is_limited("login_fail", account_key, acct_limit, acct_window):
            return too_many("Too many failed attempts for this account.", "login_fail", account_key, acct_window)
        if ratelimit.is_limited("login_fail_ip", ip, ip_limit, ip_window):
            return too_many("Too many failed attempts from your network.", "login_fail_ip", ip, ip_window)

        user = users_model.authenticate(username, str(data.get("password") or ""))
        if user is None:
            ratelimit.record("login_fail", account_key)
            ratelimit.record("login_fail_ip", ip)
            target_id = users_model.get_id_by_username(username)
            if target_id:
                users_model.record_login(target_id, False, ip)
            abort(401, "Wrong username or password.")
        ratelimit.clear("login_fail", account_key)
        failed = users_model.failed_since_last_login(user["id"])
        users_model.record_login(user["id"], True, ip)
        return session_for(user, failed_attempts=failed)

    @app.get("/me")
    @login_required
    def me():
        return jsonify(user=public_user(g.user), logins=users_model.recent_logins(g.user["id"]))

    @app.post("/me/password")
    @login_required
    def change_password():
        data = body()
        try:
            users_model.change_password(g.user["id"], str(data.get("current") or ""), str(data.get("new") or ""))
        except users_model.AccountError as e:
            abort(400, str(e))
        # Every older token is now invalid; give this session a fresh one.
        return session_for(users_model.get_by_id(g.user["id"]))

    @app.delete("/me")
    @login_required
    def delete_account():
        data = body()
        try:
            users_model.check_can_delete(g.user["id"], str(data.get("password") or ""))
        except users_model.AccountError as e:
            abort(400, str(e))
        try:
            progress.delete_user_logs(g.token)
        except ProgressUnavailable:
            # Refuse rather than leave this user's logs behind (ADR 7).
            abort(503, "Your progress logs can't be deleted right now, so the account was kept. Try again shortly.")
        users_model.delete_user(g.user["id"])
        return "", 204

    # ── Roadmap items ───────────────────────────────────────────────────────

    def item_fields(data):
        def text(name):
            return str(data.get(name) or "").strip()[:MAX_LEN[name]]
        try:
            priority = max(1, min(5, int(data.get("priority", 3))))
        except (TypeError, ValueError):
            priority = 3
        fields = {
            "title": text("title"),
            "type": data.get("type") if data.get("type") in ITEM_TYPES else "course",
            "platform": text("platform"),
            "url": text("url"),
            "skill_tags": text("skill_tags"),
            "difficulty": data.get("difficulty") if data.get("difficulty") in DIFFICULTIES else "beginner",
            "priority": priority,
        }
        if not fields["title"]:
            abort(400, "Title is required.")
        if fields["url"] and not fields["url"].startswith(("https://", "http://")):
            abort(400, "URL must start with http:// or https://.")   # no javascript: links in the UI
        return fields

    @app.get("/items")
    @login_required
    def list_items():
        args = request.args
        items = roadmap_model.get_all(g.user["id"], status=args.get("status") or None,
                                      skill=args.get("skill") or None, search=args.get("search") or None,
                                      type_=args.get("type") or None)
        return jsonify(items=items)

    @app.get("/dashboard")
    @login_required
    def dashboard():
        uid = g.user["id"]
        return jsonify(counts=roadmap_model.get_status_counts(uid),
                       skills=roadmap_model.get_skill_summary(uid),
                       tags=roadmap_model.get_all_tags(uid))

    @app.get("/options")
    def options():
        return jsonify(types=ITEM_TYPES, platforms=PLATFORMS, difficulties=DIFFICULTIES,
                       statuses=list(roadmap_model.STATUSES))

    @app.post("/items")
    @login_required
    def create_item():
        f = item_fields(body())
        item_id = roadmap_model.create(g.user["id"], f["title"], f["type"], f["platform"], f["url"],
                                       f["skill_tags"], f["difficulty"], f["priority"])
        return jsonify(item=roadmap_model.get_by_id(item_id, g.user["id"])), 201

    @app.get("/items/<int:item_id>")
    @login_required
    def get_item(item_id):
        item = roadmap_model.get_by_id(item_id, g.user["id"])
        if item is None:
            abort(404, "Item not found.")
        return jsonify(item=item)

    @app.put("/items/<int:item_id>")
    @login_required
    def update_item(item_id):
        if roadmap_model.get_by_id(item_id, g.user["id"]) is None:
            abort(404, "Item not found.")
        roadmap_model.update(item_id, g.user["id"], **item_fields(body()))
        return jsonify(item=roadmap_model.get_by_id(item_id, g.user["id"]))

    @app.patch("/items/<int:item_id>/status")
    @login_required
    def set_status(item_id):
        status = body().get("status")
        if status not in roadmap_model.STATUSES:
            abort(400, "Unknown status.")
        if not roadmap_model.update_status(item_id, g.user["id"], status):
            abort(404, "Item not found.")
        return jsonify(item=roadmap_model.get_by_id(item_id, g.user["id"]))

    @app.delete("/items/<int:item_id>")
    @login_required
    def delete_item(item_id):
        if not roadmap_model.delete(item_id, g.user["id"]):
            abort(404, "Item not found.")
        try:
            logs_deleted = progress.delete_item_logs(g.token, item_id)
        except ProgressUnavailable:
            logs_deleted = None   # orphans stay in progress; ignored there (ADR 7)
        return jsonify(deleted=True, logs_deleted=logs_deleted)

    # ── Career timeline ─────────────────────────────────────────────────────

    def current_path(user):
        """(field, level): the saved choice, else the latest assessment, else None."""
        if _planner.is_valid(user["path_field"], user["path_level"]):
            return user["path_field"], user["path_level"]
        latest = assessment_model.history(user["id"], limit=1)
        if latest and _planner.is_valid(latest[0]["field"], latest[0]["level"]):
            return latest[0]["field"], latest[0]["level"]
        return None

    @app.get("/path")
    @login_required
    def get_path():
        path = current_path(g.user)
        return jsonify(current={"field": path[0], "level": path[1]} if path else None,
                       fields=[{"key": k, "name": n} for k, n in _planner.fields()],
                       levels=[{"key": lvl, "label": LEVEL_LABELS[lvl]} for lvl in LEVELS])

    @app.put("/path")
    @login_required
    def set_path():
        data = body()
        field, level = data.get("field"), data.get("level")
        if not _planner.is_valid(field, level):
            abort(400, "Pick a field and a level from the list.")
        users_model.set_path(g.user["id"], field, level)
        return jsonify(current={"field": field, "level": level})

    @app.get("/timeline")
    @login_required
    def timeline():
        path = current_path(g.user)
        if path is None:
            return jsonify(timeline=None)
        plan = _planner.plan(path[0], path[1], roadmap_model.get_all(g.user["id"]), date.today())
        return jsonify(timeline=jsonable(plan))

    @app.post("/timeline/phases/<int:number>")
    @login_required
    def add_phase(number):
        path = current_path(g.user)
        if path is None:
            abort(409, "Choose a career path first.")
        try:
            items = _planner.items_for_phase(path[0], number)
        except IndexError:
            abort(404, "No such phase.")
        return jsonify(added=roadmap_model.create_many(g.user["id"], items))

    # ── Career assessment ───────────────────────────────────────────────────

    @app.get("/assessments")
    @login_required
    def assessments():
        return jsonify(fields=jsonable(_quiz.fields()), history=assessment_model.history(g.user["id"]))

    @app.get("/assessments/<field>")
    @login_required
    def questions(field):
        data = _quiz.field(field)
        if data is None:
            abort(404, "Unknown field.")
        # Points stay on the server: sending them would give the answers away.
        return jsonify(field=field, name=data["name"], questions=[
            {"id": q["id"], "text": q["text"], "options": [o["text"] for o in q["options"]]}
            for q in data["questions"]
        ])

    @app.post("/assessments/<field>")
    @login_required
    def submit_assessment(field):
        if _quiz.field(field) is None:
            abort(404, "Unknown field.")
        answers = body().get("answers")
        if not isinstance(answers, dict):
            abort(400, "Expected answers as {question_id: option_index}.")
        try:
            result = _quiz.score(field, answers)
        except AssessmentError as e:
            abort(400, str(e))
        attempt_id = assessment_model.save(g.user["id"], field, result.answers, result.score,
                                           result.max_score, result.level)
        if _planner.is_valid(field, result.level):
            users_model.set_path(g.user["id"], field, result.level)   # the timeline follows the latest result
        return jsonify(id=attempt_id, result=jsonable(result)), 201

    @app.get("/assessments/results/<int:attempt_id>")
    @login_required
    def assessment_result(attempt_id):
        attempt = assessment_model.get(attempt_id, g.user["id"])
        if attempt is None:
            abort(404, "Result not found.")
        try:
            result = _quiz.score(attempt["field"], attempt["answers"])
        except AssessmentError:
            abort(410, "That result was taken on an older version of the questions. Please retake it.")
        return jsonify(result=jsonable(result), taken_at=attempt["taken_at"])

    return app



