-- 20260420000004_model_status_lifecycle.sql
-- Extend model_version_status from (active, retired) to four states.
-- Split into two migrations because Postgres requires new enum values to be
-- committed before they can be referenced in the same transaction.

-- 1) Add the new enum values. These must be committed before they can be used.
alter type model_version_status add value if not exists 'pending_review' before 'active';
alter type model_version_status add value if not exists 'approved' before 'active';
