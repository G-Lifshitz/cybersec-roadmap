"""Cross-cutting HTTP concerns, identical in both services (each keeps its own copy,
since each service is built and deployed on its own; ADR 6).

- one log line per request on stdout: method, path, status, duration
- GET /health: 200 when this service can read and write its own database, else 503
- CORS: only the UI's origin (CORS_ORIGINS) may call the API from a browser
- every error is JSON; a database that is still resuming becomes a 503 the UI
  can show as "starting up, try again" (A2 §7.5)
"""
import logging
import os
import sys
import time

from datetime import date, datetime

from flask import g, jsonify, request
from flask.json.provider import DefaultJSONProvider
from flask_cors import CORS
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

import db

log = logging.getLogger("http")


class JSONProvider(DefaultJSONProvider):
    """Dates as ISO 8601 ('2026-11-18T12:00:00') instead of Flask's HTTP-date format."""
    sort_keys = False

    @staticmethod
    def default(o):
        if isinstance(o, (date, datetime)):
            return o.isoformat()
        return DefaultJSONProvider.default(o)


def configure_logging(service):
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        stream=sys.stdout,
        format=f"%(asctime)s %(levelname)s {service} %(name)s: %(message)s",
    )


def setup(app, service):
    configure_logging(service)
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024   # reject bodies over 64 KB (413)
    app.json = JSONProvider(app)

    origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:8080").split(",") if o.strip()]
    CORS(app, origins=origins, allow_headers=["Content-Type", "Authorization"],
         methods=["GET", "POST", "PUT", "PATCH", "DELETE"], max_age=600)

    if os.environ.get("TRUST_PROXY", "0") == "1":
        # Container Apps puts exactly one proxy in front of the app. Trusting
        # one X-Forwarded-For hop gives the client's real IP to the rate limiter;
        # trusting more would let clients pick their own "IP".
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

    version = os.environ.get("GIT_SHA", "dev")

    @app.before_request
    def _start_timer():
        g.started = time.perf_counter()

    @app.after_request
    def _log_request(response):
        ms = (time.perf_counter() - g.get("started", time.perf_counter())) * 1000
        log.info("%s %s %d %.1fms", request.method, request.path, response.status_code, ms)
        return response

    @app.get("/health")
    def health():
        try:
            db.check()
            return jsonify(status="ok", db="ok", version=version), 200
        except Exception as e:  # noqa: BLE001 - any failure means unhealthy
            log.warning("health check failed: %s", e.__class__.__name__)
            return jsonify(status="error", db="unavailable", version=version), 503

    @app.errorhandler(db.DatabaseUnavailable)
    @app.errorhandler(db.OperationalError)
    def _db_down(_):
        resp = jsonify(error="starting_up",
                       message="The service is starting up. Try again in a minute.")
        resp.status_code = 503
        resp.headers["Retry-After"] = "30"
        return resp

    @app.errorhandler(HTTPException)
    def _http_error(e):
        resp = jsonify(error=e.name.lower().replace(" ", "_"), message=e.description)
        resp.status_code = e.code
        return resp

    @app.errorhandler(Exception)
    def _unexpected(e):
        log.exception("unhandled error")
        return jsonify(error="internal_error", message="Something went wrong."), 500
