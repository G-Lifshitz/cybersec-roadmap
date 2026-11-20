"""Progress service: progress logs, the study summary and the stats page data.

JSON API only; endpoints are listed in openapi.yaml. The token is verified
locally (shared TOKEN_SECRET, see auth.py); anything about an item (does it
exist, is it yours, what are its tags) is asked of the roadmap service.

Partial failure (A2 §3), with the roadmap service stopped:
- reading logs for an item, deleting logs: work (progress's own data only)
- logging progress: 503 with a clear message. The log isn't saved, because
  progress can't check that the item exists and is the caller's.
- summary and stats: degraded. Totals, streaks and the calendar are still
  computed from progress's own data; the parts needing skill tags (weak
  skills, minutes per skill) are left out and roadmap_available is false.
"""
from datetime import date
from functools import wraps

from flask import Flask, abort, g, jsonify, request

import auth
import models.progress as progress_model
import web
from domain import insights, stats
from roadmap_client import RoadmapClient, RoadmapUnavailable
from serialize import jsonable

MAX_NOTES = 2000
MAX_MINUTES = 24 * 60


def create_app(roadmap=None):
    app = Flask(__name__)
    web.setup(app, "progress")
    roadmap = roadmap or RoadmapClient()

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            token = auth.bearer(request.headers)
            if not token:
                abort(401, "Log in first.")
            try:
                g.user_id, _epoch = auth.verify(token)
            except auth.InvalidToken:
                abort(401, "Your session has expired. Log in again.")
            g.token = token
            return view(*args, **kwargs)
        return wrapped

    def roadmap_down():
        resp = jsonify(error="roadmap_unavailable",
                       message="Your roadmap can't be reached right now, so progress wasn't saved. Try again shortly.")
        resp.status_code = 503
        resp.headers["Retry-After"] = "30"
        return resp

    def tags_or_none():
        """{item_id: tags} from roadmap, or None when roadmap is unavailable (degraded mode)."""
        try:
            return roadmap.tags_by_item(g.token)
        except RoadmapUnavailable:
            return None
        except PermissionError:
            abort(401, "Your session has expired. Log in again.")

    # ── Logs ────────────────────────────────────────────────────────────────

    @app.get("/items/<int:item_id>/logs")
    @login_required
    def item_logs(item_id):
        logs = progress_model.get_logs_for_item(g.user_id, item_id)
        return jsonify(logs=logs, completion=logs[0]["completion_pct"] if logs else 0)

    @app.post("/items/<int:item_id>/logs")
    @login_required
    def add_log(item_id):
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            abort(400, "Expected a JSON object.")
        try:
            pct = max(0, min(100, int(data.get("completion_pct", 0))))
            mins = max(0, min(MAX_MINUTES, int(data.get("time_spent_mins") or 0)))
        except (TypeError, ValueError):
            abort(400, "Completion and time must be numbers.")
        felt = data.get("felt_difficulty")
        notes = str(data.get("notes") or "").strip()[:MAX_NOTES]

        # Cross-seam flow (server side): the item must exist and be the
        # caller's before a log can point at it. This replaces the foreign key.
        try:
            item = roadmap.get_item(g.token, item_id)
        except RoadmapUnavailable:
            return roadmap_down()
        except PermissionError:
            abort(401, "Your session has expired. Log in again.")
        if item is None:
            abort(404, "Item not found.")

        log_id = progress_model.add_log(g.user_id, item_id, pct,
                                        felt if felt in progress_model.FELT_DIFFICULTIES else None,
                                        notes, mins)

        # Then sync the item's status, as Assignment 1's add_log() did with a
        # cross-table UPDATE. The log is already saved; if roadmap fails now,
        # say so instead of failing the whole request.
        new_status = insights.status_for_completion(pct)
        status_synced = True
        if new_status and new_status != item["status"]:
            try:
                roadmap.set_status(g.token, item_id, new_status)
            except Exception:  # noqa: BLE001 - RoadmapUnavailable or an HTTP error
                status_synced = False
        return jsonify(id=log_id, item_status=new_status or item["status"], status_synced=status_synced), 201

    @app.delete("/items/<int:item_id>/logs")
    @login_required
    def delete_item_logs(item_id):
        return jsonify(deleted=progress_model.delete_for_item(g.user_id, item_id))

    @app.get("/logs")
    @login_required
    def all_logs():
        return jsonify(logs=progress_model.all_logs(g.user_id))

    @app.delete("/logs")
    @login_required
    def delete_all_logs():
        return jsonify(deleted=progress_model.delete_for_user(g.user_id))

    # ── Summary and stats ───────────────────────────────────────────────────

    @app.get("/summary")
    @login_required
    def summary():
        """Dashboard numbers: completion per item, total time, weak skills."""
        tags = tags_or_none()
        entries = progress_model.time_entries(g.user_id)
        if tags is not None:
            entries = [e for e in entries if e["item_id"] in tags]   # ignore orphans of deleted items
        return jsonify(
            completion={str(k): v for k, v in progress_model.latest_completion_by_item(g.user_id).items()},
            total_minutes=sum(e["minutes"] for e in entries),
            weak_skills=None if tags is None else insights.weak_skills(progress_model.rated_logs(g.user_id), tags),
            roadmap_available=tags is not None,
        )

    @app.get("/stats")
    @login_required
    def stats_report():
        today = date.today()
        year, month = stats.parse_month(request.args.get("month"), today)
        tags = tags_or_none()
        rows = progress_model.time_entries(g.user_id)
        if tags is not None:
            rows = [r for r in rows if r["item_id"] in tags]
        report = stats.build_report(stats.to_entries(insights.with_tags(rows, tags)), today, year, month)
        out = jsonable(report)
        if tags is None:
            out["skills"] = None   # minutes per skill needs the roadmap's tags
        return jsonify(report=out, roadmap_available=tags is not None)

    return app
