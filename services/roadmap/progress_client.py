"""HTTP client for the progress service: the roadmap side of the seam.

Roadmap calls progress in two places, both to clean up logs that used to go
with ON DELETE CASCADE when everything was one database (ADR 7):

- deleting an item: best effort. If progress is down the item is still
  deleted and its logs stay behind as orphans, which progress ignores because
  every report starts from the items roadmap returns.
- deleting the account: required. Personal data must not survive the
  account (right to erasure), so if progress is down the account deletion is
  refused with 503 and the user can retry.

Base URL from PROGRESS_URL, timeout from PROGRESS_TIMEOUT_S (default 2 s). The
caller's bearer token is forwarded, so progress deletes only that user's logs.
"""
import logging
import os

import requests

log = logging.getLogger(__name__)


class ProgressUnavailable(RuntimeError):
    pass


class ProgressClient:
    def __init__(self, base_url=None, timeout_s=None, session=None):
        self.base_url = (base_url or os.environ.get("PROGRESS_URL", "http://progress:8000")).rstrip("/")
        self.timeout_s = float(timeout_s if timeout_s is not None else os.environ.get("PROGRESS_TIMEOUT_S", 2))
        self.http = session or requests.Session()

    def _delete(self, path, token):
        try:
            resp = self.http.delete(f"{self.base_url}{path}", timeout=self.timeout_s,
                                    headers={"Authorization": f"Bearer {token}"})
        except requests.RequestException as e:
            log.warning("progress call failed: DELETE %s: %s", path, e.__class__.__name__)
            raise ProgressUnavailable(str(e)) from e
        if resp.status_code >= 400:
            log.warning("progress call failed: DELETE %s -> %d", path, resp.status_code)
            raise ProgressUnavailable(f"progress answered {resp.status_code}")
        return resp.json().get("deleted", 0)

    def delete_item_logs(self, token, item_id):
        return self._delete(f"/items/{int(item_id)}/logs", token)

    def delete_user_logs(self, token):
        return self._delete("/logs", token)
