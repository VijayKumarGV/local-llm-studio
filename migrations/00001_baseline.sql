-- Baseline migration: schema is bootstrapped by backend/database.py init_db()
-- and backend/rag.py ensure_schema(). This file exists so yoyo has a first
-- migration to record; future schema changes should be added as
-- 00002_*.sql, 00003_*.sql, etc. and applied via backend/migrations.py.

-- No-op statement so yoyo has something to execute.
SELECT 1;
