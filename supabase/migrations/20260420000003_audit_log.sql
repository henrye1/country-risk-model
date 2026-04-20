-- 20260420000003_audit_log.sql
-- Append-only audit trail. Application code writes rows; no triggers.

create table audit_log (
  id uuid primary key default gen_random_uuid(),
  actor_user_id uuid references auth.users (id),
  action text not null,              -- e.g. 'snapshot.publish', 'snapshot.create'
  entity_type text not null,         -- e.g. 'score_snapshot'
  entity_id uuid,                    -- nullable because some actions are not entity-scoped
  before_json jsonb,
  after_json jsonb,
  at timestamptz not null default now()
);

create index audit_log_entity_idx on audit_log (entity_type, entity_id, at desc);
create index audit_log_actor_idx on audit_log (actor_user_id, at desc);

alter table audit_log enable row level security;

create policy "audit_log: internal read"
on audit_log for select
using ((select org_status from app.current_membership()) = 'internal');

-- Writes via service_role only.
