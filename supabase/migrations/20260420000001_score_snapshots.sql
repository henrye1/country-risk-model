-- 20260420000001_score_snapshots.sql
-- Score snapshot tables: the audit-critical output of the scoring pipeline.
--
-- score_snapshots     = one row per scoring run (draft → published → archived).
-- country_scores      = top-level score per country per snapshot.
-- driver_scores       = full drill-down per driver per country per snapshot.
--
-- Immutability triggers live in a separate migration.

create type snapshot_status as enum ('draft', 'published', 'archived');

create table score_snapshots (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  as_of_date date not null,
  status snapshot_status not null default 'draft',

  -- Which model version was used per segment. NULL means "none for this segment",
  -- which is valid if no country in the segment was scorable this run.
  model_version_high   uuid references model_versions (id) on delete restrict,
  model_version_low    uuid references model_versions (id) on delete restrict,
  model_version_nodata uuid references model_versions (id) on delete restrict,

  created_by    uuid references auth.users (id),
  created_at    timestamptz not null default now(),
  published_by  uuid references auth.users (id),
  published_at  timestamptz,
  published_notes text
);

create index score_snapshots_status_idx on score_snapshots (status, as_of_date desc);
create index score_snapshots_published_idx on score_snapshots (status, published_at desc)
  where status = 'published';

create table country_scores (
  snapshot_id  uuid not null references score_snapshots (id) on delete cascade,
  iso3         char(3) not null references countries (iso3),
  segment      segment_code not null,
  final_score  numeric not null,
  quant_score  numeric not null,
  qual_score   numeric not null,
  bucket_band  text,
  primary key (snapshot_id, iso3)
);

create index country_scores_iso3_idx on country_scores (iso3);

create table driver_scores (
  snapshot_id        uuid not null references score_snapshots (id) on delete cascade,
  iso3               char(3) not null references countries (iso3),
  variable_code      text not null references variables (code),
  raw_value          numeric,
  standardised_value numeric,
  bucket_score       numeric,
  contribution       numeric not null,
  primary key (snapshot_id, iso3, variable_code)
);

create index driver_scores_variable_idx on driver_scores (variable_code);

alter table score_snapshots enable row level security;
alter table country_scores  enable row level security;
alter table driver_scores   enable row level security;

-- Published scores readable by any authenticated user (PD/LGD consumers + clients).
create policy "published scores: any authenticated read"
on country_scores for select
to authenticated
using (
  exists (
    select 1 from score_snapshots s
    where s.id = snapshot_id and s.status = 'published'
  )
);

create policy "published drivers: any authenticated read"
on driver_scores for select
to authenticated
using (
  exists (
    select 1 from score_snapshots s
    where s.id = snapshot_id and s.status = 'published'
  )
);

create policy "published snapshots: any authenticated read"
on score_snapshots for select
to authenticated
using (status = 'published');

-- Draft + archived visible only to internal org members.
create policy "draft/archived snapshots: internal read"
on score_snapshots for select
using (
  status in ('draft', 'archived')
  and (select org_status from app.current_membership()) = 'internal'
);

create policy "draft scores: internal read"
on country_scores for select
using (
  exists (
    select 1 from score_snapshots s
    where s.id = snapshot_id
      and s.status in ('draft', 'archived')
  )
  and (select org_status from app.current_membership()) = 'internal'
);

create policy "draft drivers: internal read"
on driver_scores for select
using (
  exists (
    select 1 from score_snapshots s
    where s.id = snapshot_id
      and s.status in ('draft', 'archived')
  )
  and (select org_status from app.current_membership()) = 'internal'
);

-- Writes restricted to service_role. No authenticated-user INSERT/UPDATE/DELETE policies → blocked by RLS.
