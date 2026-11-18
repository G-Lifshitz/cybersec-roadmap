"""SQL Server access for this service.

DATABASE_URL has the SQLAlchemy form, so the same string works locally and on
Azure (only host, database, user and password change):

    mssql+pymssql://<user>:<password>@<host>:1433/<database>

Characters such as @ : / in the password must be URL-encoded (%40, %3A, %2F).

Pattern: Singleton (Creational), kept from Assignment 1. There is one Database
object per process. It hands each worker thread its own connection
(threading.local), so threads never share a transaction, which was the
trade-off noted in Assignment 1's SQLite version.

Cold starts: Azure SQL serverless pauses after 60 idle minutes and takes up to
about a minute to resume. Connections fail meanwhile (error 40613, or a
pymssql DB-Lib 20002/20003 timeout), so connect() retries with exponential
backoff until CONNECT_DEADLINE_S has passed.
"""
import logging
import os
import threading
import time
from contextlib import contextmanager
from urllib.parse import parse_qs, unquote, urlparse

import pymssql

log = logging.getLogger(__name__)

# A cached connection unused for this long is pinged before it's reused; the
# database may have paused in between and closed it.
IDLE_PING_S = 60


class DatabaseUnavailable(RuntimeError):
    """The database could not be reached before the deadline."""


def parse_url(url):
    """Split a mssql+pymssql:// URL into pymssql.connect() keyword arguments."""
    parsed = urlparse(url or "")
    if parsed.scheme not in ("mssql+pymssql", "mssql"):
        raise ValueError("DATABASE_URL must start with mssql+pymssql://")
    if not parsed.hostname or not parsed.path.strip("/"):
        raise ValueError("DATABASE_URL needs a host and a database name")
    options = {k: v[-1] for k, v in parse_qs(parsed.query).items()}
    kwargs = {
        "server": parsed.hostname,
        "port": str(parsed.port or 1433),
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": parsed.path.strip("/"),
        "login_timeout": int(options.get("login_timeout", 10)),
        "timeout": int(options.get("timeout", 30)),
        "autocommit": False,
    }
    # Azure SQL only accepts encrypted connections. FreeTDS (inside pymssql)
    # asks for encryption by default; ?encryption=require makes it mandatory.
    if "encryption" in options:
        kwargs["encryption"] = options["encryption"]
    return kwargs


class Database:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._local = threading.local()
        return cls._instance

    @property
    def url(self):
        return os.environ.get("DATABASE_URL", "")

    def connect(self, deadline_s=None):
        """Open a new connection, retrying with backoff while the database is unreachable."""
        if deadline_s is None:
            deadline_s = float(os.environ.get("DB_CONNECT_DEADLINE_S", 90))
        kwargs = parse_url(self.url)
        stop_at = time.monotonic() + deadline_s
        delay, attempt = 1.0, 0
        while True:
            attempt += 1
            try:
                return pymssql.connect(**kwargs)
            except (pymssql.OperationalError, pymssql.InterfaceError) as e:
                if time.monotonic() + delay > stop_at:
                    raise DatabaseUnavailable(f"database unreachable after {attempt} attempts: {e}") from e
                log.warning("database not ready (attempt %d), retrying in %.0fs: %s", attempt, delay, e)
                time.sleep(delay)
                delay = min(delay * 2, 10)

    def connection(self):
        """This thread's connection, (re)opened if missing or dead."""
        local = self._local
        conn = getattr(local, "conn", None)
        if conn is not None and time.monotonic() - local.last_used > IDLE_PING_S:
            try:
                cur = conn.cursor()
                cur.execute("SELECT 1")
                cur.fetchall()
            except Exception:  # noqa: BLE001 - any failure means the connection is unusable
                self.discard()
                conn = None
        if conn is None:
            conn = local.conn = self.connect()
        local.last_used = time.monotonic()
        return conn

    def discard(self):
        conn = getattr(self._local, "conn", None)
        self._local.conn = None
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


_db = Database()


@contextmanager
def transaction():
    """Yield a dict cursor; commit on success, roll back on error.

        with transaction() as cur:
            cur.execute("SELECT * FROM roadmap_items WHERE id = %s", (item_id,))
            row = cur.fetchone()

    A connection error throws the connection away, so the next request
    reconnects instead of reusing a dead handle.
    """
    conn = _db.connection()
    cur = conn.cursor(as_dict=True)
    try:
        yield cur
        conn.commit()
    except (pymssql.OperationalError, pymssql.InterfaceError):
        _db.discard()
        raise
    except Exception:
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            _db.discard()
        raise


def check():
    """Read and write this service's own database. Used by GET /health."""
    with transaction() as cur:
        cur.execute("UPDATE health_check SET checked_at = SYSUTCDATETIME() WHERE id = 1")
        cur.execute("SELECT checked_at FROM health_check WHERE id = 1")
        return cur.fetchone() is not None


IntegrityError = pymssql.IntegrityError
OperationalError = pymssql.OperationalError
