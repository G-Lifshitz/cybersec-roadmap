-- 001: the roadmap service's schema, ported from the Assignment 1 SQLite schema
-- (db.py init_db + _migrate). Owns accounts and everything the user plans;
-- progress_logs moved to the progress service's own database (ADR 6).
--
-- SQLite -> SQL Server: INTEGER PRIMARY KEY AUTOINCREMENT -> INT IDENTITY,
-- TEXT -> NVARCHAR, TIMESTAMP DEFAULT CURRENT_TIMESTAMP -> DATETIME2 DEFAULT
-- SYSUTCDATETIME(), COLLATE NOCASE -> a case-insensitive collation.

CREATE TABLE users (
    id              INT IDENTITY(1,1) PRIMARY KEY,
    username        NVARCHAR(30) COLLATE Latin1_General_CI_AS NOT NULL,
    password_hash   NVARCHAR(255) NOT NULL,
    is_admin        BIT NOT NULL DEFAULT 0,
    session_epoch   INT NOT NULL DEFAULT 0,      -- bumped on password change; older tokens stop working
    path_field      NVARCHAR(50) NULL,           -- key in domain/timeline_catalog.py
    path_level      NVARCHAR(20) NULL,           -- none | beginner | intermediate | advanced
    github_username NVARCHAR(39) NULL,
    created_at      DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT uq_users_username UNIQUE (username)  -- case-insensitive: "Georgy" = "georgy"
);

CREATE TABLE login_events (
    id         INT IDENTITY(1,1) PRIMARY KEY,
    user_id    INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    success    BIT NOT NULL,
    ip         NVARCHAR(64) NULL,
    created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
CREATE INDEX idx_login_events_user ON login_events(user_id, id);

CREATE TABLE roadmap_items (
    id         INT IDENTITY(1,1) PRIMARY KEY,
    user_id    INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title      NVARCHAR(200) NOT NULL,
    type       NVARCHAR(20) NOT NULL,
    platform   NVARCHAR(50) NULL,
    url        NVARCHAR(500) NULL,
    skill_tags NVARCHAR(200) NULL,
    difficulty NVARCHAR(20) NOT NULL DEFAULT 'beginner',
    priority   INT NOT NULL DEFAULT 3,
    status     NVARCHAR(20) NOT NULL DEFAULT 'not_started',
    created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
CREATE INDEX idx_items_user ON roadmap_items(user_id);

CREATE TABLE rate_events (
    id         INT IDENTITY(1,1) PRIMARY KEY,
    kind       NVARCHAR(20) NOT NULL,    -- 'login_fail', 'login_fail_ip', 'register'
    [key]      NVARCHAR(120) NOT NULL,   -- username|ip, or ip
    created_at FLOAT NOT NULL            -- unix time, seconds
);
CREATE INDEX idx_rate_lookup ON rate_events(kind, [key], created_at);

CREATE TABLE assessments (
    id        INT IDENTITY(1,1) PRIMARY KEY,
    user_id   INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    field     NVARCHAR(50) NOT NULL,     -- key in domain/question_bank.py
    answers   NVARCHAR(MAX) NOT NULL,    -- JSON {question_id: option_index}
    score     INT NOT NULL,
    max_score INT NOT NULL,
    level     NVARCHAR(20) NOT NULL,
    taken_at  DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
CREATE INDEX idx_assessments_user ON assessments(user_id, id);

-- One row that GET /health updates and reads back, proving the service can
-- both write and read its own database.
CREATE TABLE health_check (
    id         INT PRIMARY KEY,
    checked_at DATETIME2 NOT NULL
);
INSERT INTO health_check (id, checked_at) VALUES (1, SYSUTCDATETIME());
