-- 002: remember when each roadmap item last changed.
--
-- Changes a table that already holds data (A2 §4), without losing a row:
--  1. add the column as NULL, so existing rows are accepted as they are;
--  2. backfill it from created_at, the best value we have for old rows;
--  3. only then make it NOT NULL with a default for new rows.
-- The runner applies the three batches in one transaction: all or nothing.

ALTER TABLE roadmap_items ADD updated_at DATETIME2 NULL;
GO

UPDATE roadmap_items SET updated_at = created_at WHERE updated_at IS NULL;
GO

ALTER TABLE roadmap_items ALTER COLUMN updated_at DATETIME2 NOT NULL;
ALTER TABLE roadmap_items ADD CONSTRAINT df_items_updated_at DEFAULT SYSUTCDATETIME() FOR updated_at;
