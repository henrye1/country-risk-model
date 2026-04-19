-- 20260419000005_raw_observations.sql
-- Ingestion tables: append-only raw observations + upload provenance.

create type observation_source as enum ('EIU', 'WB', 'WGI', 'OTHER');

create table data_uploads (
  id uuid primary key default gen_random_uuid(),
  uploaded_by uuid references auth.users (id),
  source observation_source not null,
  file_name text,                 -- nullable: null for API pulls
  row_count int not null default 0,
  notes text,
  uploaded_at timestamptz not null default now()
);

create index data_uploads_source_idx on data_uploads (source, uploaded_at desc);

create table raw_observations (
  id uuid primary key default gen_random_uuid(),
  iso3 char(3) not null references countries (iso3) on delete cascade,
  variable_code text not null references variables (code),
  year int not null,
  value numeric,                  -- null = API returned no value for this country-year
  source observation_source not null,
  upload_id uuid references data_uploads (id) on delete set null,
  ingested_at timestamptz not null default now(),
  ingested_by uuid references auth.users (id)
);

-- Look-ups against raw_observations almost always filter by country + variable + year,
-- ordering by ingested_at desc (latest-wins semantics for corrections).
create index raw_observations_key_idx
  on raw_observations (iso3, variable_code, year, ingested_at desc);

create index raw_observations_upload_idx on raw_observations (upload_id);

alter table data_uploads      enable row level security;
alter table raw_observations  enable row level security;

create policy "data_uploads: internal read"
on data_uploads for select
using ((select org_status from app.current_membership()) = 'internal');

create policy "raw_observations: internal read"
on raw_observations for select
using ((select org_status from app.current_membership()) = 'internal');

-- Writes to these tables restricted to service_role (backend admin path). No
-- INSERT/UPDATE/DELETE policies for authenticated users → blocked by RLS.
