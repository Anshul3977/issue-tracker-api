-- List-query index for GET /api/v1/issues.
-- Matches WHERE project_id = ? AND state = ? ORDER BY created_at DESC, id DESC LIMIT ?.
-- The foreign-key index on project_id stays either way; this is the one the
-- benchmark drops and recreates. Do not edit one copy without the other:
-- alembic/versions/0001_initial.py reads this file.
CREATE INDEX ix_issues_project_state_created_id
    ON issues (project_id, state, created_at DESC, id DESC);
