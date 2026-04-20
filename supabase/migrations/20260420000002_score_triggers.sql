-- 20260420000002_score_triggers.sql
-- Immutability: published country_scores + driver_scores cannot be UPDATEd or DELETEd.
-- Status transitions: draft → published, published → archived. No other transitions.

-- Helper: look up the status of the snapshot that "owns" a score row.
create or replace function app.score_row_snapshot_status(p_snapshot_id uuid)
returns snapshot_status
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select status from score_snapshots where id = p_snapshot_id;
$$;

-- Reject UPDATE/DELETE on country_scores rows belonging to a published snapshot.
create or replace function app.reject_mutation_on_published_score()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  snap_status snapshot_status;
begin
  snap_status := app.score_row_snapshot_status(coalesce(new.snapshot_id, old.snapshot_id));
  if snap_status = 'published' then
    raise exception 'cannot modify rows of a published snapshot (table: %, snapshot_id: %)',
      tg_table_name, coalesce(new.snapshot_id, old.snapshot_id)
      using errcode = 'check_violation';
  end if;
  return coalesce(new, old);
end;
$$;

create trigger country_scores_immutable_when_published
before update or delete on country_scores
for each row execute function app.reject_mutation_on_published_score();

create trigger driver_scores_immutable_when_published
before update or delete on driver_scores
for each row execute function app.reject_mutation_on_published_score();

-- Enforce valid status transitions on score_snapshots.
create or replace function app.enforce_snapshot_status_transitions()
returns trigger
language plpgsql
as $$
begin
  -- Allow INSERT without restriction (default is 'draft').
  if tg_op = 'INSERT' then
    return new;
  end if;

  -- No-op updates (status unchanged) are allowed.
  if old.status = new.status then
    return new;
  end if;

  -- draft → published
  if old.status = 'draft' and new.status = 'published' then
    return new;
  end if;

  -- published → archived
  if old.status = 'published' and new.status = 'archived' then
    return new;
  end if;

  raise exception 'invalid snapshot status transition: % → %', old.status, new.status
    using errcode = 'check_violation';
end;
$$;

create trigger score_snapshots_status_transitions
before insert or update on score_snapshots
for each row execute function app.enforce_snapshot_status_transitions();
