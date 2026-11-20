-- 001: the progress service's schema. Owns what the user has actually done.
--
-- Two changes from the Assignment 1 table, both because roadmap_items is now
-- in another database (ADR 6, ADR 7):
--  * item_id is a plain ID. The FOREIGN KEY ... ON DELETE CASCADE to
--    roadmap_items can't cross databases; the service checks the item with the
--    roadmap service before inserting, and roadmap asks progress to delete an
--    item's logs when the item is deleted.
--  * user_id is new. In Assignment 1 ownership came through a JOIN on
--    roadmap_items (ADR 3); without the JOIN every log carries its owner.

CREATE TABLE progress_logs (
    id              INT IDENTITY(1,1) PRIMARY KEY,
    user_id         INT NOT NULL,
    item_id         INT NOT NULL,
    checked_in_at   DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    completion_pct  INT NOT NULL DEFAULT 0,
    felt_difficulty NVARCHAR(10) NULL,     -- easy | fair | hard | brutal
    notes           NVARCHAR(2000) NULL,
    time_spent_mins INT NULL,
    CONSTRAINT ck_logs_pct CHECK (completion_pct BETWEEN 0 AND 100)
);
CREATE INDEX idx_logs_user_item ON progress_logs(user_id, item_id);

CREATE TABLE health_check (
    id         INT PRIMARY KEY,
    checked_at DATETIME2 NOT NULL
);
INSERT INTO health_check (id, checked_at) VALUES (1, SYSUTCDATETIME());
