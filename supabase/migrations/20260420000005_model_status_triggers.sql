-- 20260420000005_model_status_triggers.sql
-- Apply default, transition guard, and auto-retire trigger now that the new
-- enum values (pending_review, approved) have been committed by migration
-- 20260420000004_model_status_lifecycle.sql.

-- 2) Default new rows to 'pending_review' (was 'active').
alter table model_versions alter column status set default 'pending_review';

-- 3) Status transition guard: only allow pending_review→approved, approved→active,
-- and any-status→retired. Reject everything else.
create or replace function app.enforce_model_version_status_transitions()
returns trigger
language plpgsql
as $$
begin
  -- Allow INSERT freely (default is now pending_review; CLI/script may also seed 'active' historically).
  if tg_op = 'INSERT' then
    return new;
  end if;

  -- No-op updates (status unchanged) are allowed.
  if old.status = new.status then
    return new;
  end if;

  -- Allowed transitions
  if old.status = 'pending_review' and new.status in ('approved', 'retired') then
    return new;
  end if;
  if old.status = 'approved' and new.status in ('active', 'retired') then
    return new;
  end if;
  if old.status = 'active' and new.status = 'retired' then
    return new;
  end if;

  raise exception 'invalid model_version status transition: % → %', old.status, new.status
    using errcode = 'check_violation';
end;
$$;

create trigger model_versions_status_transitions
before insert or update on model_versions
for each row execute function app.enforce_model_version_status_transitions();

-- 4) Auto-retire other active models in the same segment when a model becomes active.
-- Runs AFTER UPDATE so the trigger above won't reject our own update of siblings.
create or replace function app.retire_other_active_in_segment()
returns trigger
language plpgsql
as $$
begin
  if new.status = 'active' and (old.status is distinct from 'active') then
    update model_versions
      set status = 'retired'
      where segment = new.segment
        and id <> new.id
        and status = 'active';
  end if;
  return new;
end;
$$;

create trigger model_versions_auto_retire_on_activate
after update on model_versions
for each row execute function app.retire_other_active_in_segment();
