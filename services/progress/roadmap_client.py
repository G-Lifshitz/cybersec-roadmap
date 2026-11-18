"""HTTP client for the roadmap service: the progress side of the seam.

The base URL comes from ROADMAP_URL (http://roadmap:8000 in compose) and every
call has a timeout (ROADMAP_TIMEOUT_S, default 2 s), so a slow or stopped
roadmap service can never hang a progress request.

The caller's own bearer token is forwarded, so roadmap applies its usual
ownership checks: progress can only ever see or change the caller's items,
and no extra service-to-service credential is needed.

Anything other than an answer from roadmap (connection refused, timeout,
5xx, or a 503 while it cold-starts) raises RoadmapUnavailable, which each
route turns into a designed response (ADR 6, system.yaml on_failure).
"""
import logging
import os

import requests

log = logging.getLogger(__name__)


class RoadmapUnavailable(RuntimeError):
    """The roadmap service didn't answer in time or answered with a server error."""


class RoadmapClient:
    def __init__(self, base_url=None, timeout_s=None, session=None):
        self.base_url = (base_url or os.environ.get("ROADMAP_URL", "http://roadmap:8000")).rstrip("/")
        self.timeout_s = float(timeout_s if timeout_s is not None else os.environ.get("ROADMAP_TIMEOUT_S", 2))
        self.http = session or requests.Session()

    def _call(self, method, path, token, **kwargs):
        url = f"{self.base_url}{path}"
        try:
            resp = self.http.request(method, url, timeout=self.timeout_s,
                                     headers={"Authorization": f"Bearer {token}"}, **kwargs)
        except requests.RequestException as e:
            log.warning("roadmap call failed: %s %s: %s", method, path, e.__class__.__name__)
            raise RoadmapUnavailable(str(e)) from e
        if resp.status_code >= 500:
            log.warning("roadmap call failed: %s %s -> %d", method, path, resp.status_code)
            raise RoadmapUnavailable(f"roadmap answered {resp.status_code}")
        return resp

    def get_item(self, token, item_id):
        """The item as a dict, or None if it doesn't exist or isn't the caller's."""
        resp = self._call("GET", f"/items/{int(item_id)}", token)
        if resp.status_code == 404:
            return None
        if resp.status_code == 401:
            raise PermissionError("token rejected by roadmap")
        resp.raise_for_status()
        return resp.json()["item"]

    def set_status(self, token, item_id, status):
        """Sync an item's status after a log (Assignment 1's cross-table UPDATE)."""
        resp = self._call("PATCH", f"/items/{int(item_id)}/status", token, json={"status": status})
        resp.raise_for_status()

    def tags_by_item(self, token):
        """{item_id: skill_tags} for every item the caller has."""
        resp = self._call("GET", "/items", token)
        if resp.status_code == 401:
            raise PermissionError("token rejected by roadmap")
        resp.raise_for_status()
        return {item["id"]: item.get("skill_tags") or "" for item in resp.json()["items"]}
