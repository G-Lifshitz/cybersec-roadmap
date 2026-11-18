"""Versioned migrations: migrations/NNN_name.sql, applied in order, each exactly once.

Applied versions are recorded in schema_migrations, so a second boot applies
nothing. A migration file runs inside one transaction (SQL Server DDL is
transactional): it either applies completely or not at all. Lines containing
only GO split a file into batches, like sqlcmd.

sp_getapplock serialises the runner, so even two replicas starting at once
(max replicas is 1 on Azure, so this shouldn't happen) apply each file once.

Rules (ADR 7): applied files are never edited; a correction is a new file.
Forward-only: there are no down-migrations.

Run on startup:  python migrate.py   (the Dockerfile does this before gunicorn)
"""
import logging
import os
import re
import sys

import db

log = logging.getLogger("migrate")

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrations")
FILE_RE = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")
GO_RE = re.compile(r"^\s*GO\s*$", re.IGNORECASE | re.MULTILINE)


def pending_files(directory, applied):
    """Migration file names not yet applied, in version order."""
    names = sorted(n for n in os.listdir(directory) if FILE_RE.match(n))
    versions = [FILE_RE.match(n).group(1) for n in names]
    if len(versions) != len(set(versions)):
        raise RuntimeError(f"two migration files share a version number in {directory}")
    return [n for n in names if n not in applied]


def batches(sql):
    """Split a file on GO lines, dropping empty batches."""
    return [b.strip() for b in GO_RE.split(sql) if b.strip()]


def _ensure_table(cur):
    cur.execute("""
        IF OBJECT_ID('dbo.schema_migrations', 'U') IS NULL
            CREATE TABLE dbo.schema_migrations (
                version    NVARCHAR(200) NOT NULL PRIMARY KEY,
                applied_at DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
            )
    """)


def run(directory=MIGRATIONS_DIR):
    """Apply every pending migration. Returns the list of files applied."""
    with db.transaction() as cur:
        _ensure_table(cur)
    applied_now = []
    while True:
        with db.transaction() as cur:
            # Held until this transaction ends; a second runner waits here.
            cur.execute("EXEC sp_getapplock @Resource = 'schema_migrations', "
                        "@LockMode = 'Exclusive', @LockOwner = 'Transaction', @LockTimeout = 60000")
            cur.execute("SELECT version FROM dbo.schema_migrations")
            applied = {row["version"] for row in cur.fetchall()}
            todo = pending_files(directory, applied)
            if not todo:
                break
            name = todo[0]
            with open(os.path.join(directory, name), encoding="utf-8") as f:
                for batch in batches(f.read()):
                    cur.execute(batch)
            cur.execute("INSERT INTO dbo.schema_migrations (version) VALUES (%s)", (name,))
        log.info("migration applied: %s", name)
        applied_now.append(name)
    log.info("migrations up to date (%d applied on this start)", len(applied_now))
    return applied_now


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # Wait longer than a normal request would: the database may be resuming.
    db._db.connect(deadline_s=float(os.environ.get("DB_STARTUP_DEADLINE_S", 180))).close()
    run()
