-- 20260419000001_tenancy.sql
-- Tenancy: organisations and memberships. RLS enabled; policies added in a later migration.

-- Schema 'app' holds helper functions used by RLS policies (keeps public clean).
create schema if not exists app;
grant usage on schema app to anon, authenticated, service_role;

create type organisation_status as enum ('internal', 'client', 'system');
create type user_role as enum (
  'internal_owner',
  'internal_analyst',
  'client_admin',
  'client_user',
  'service_reader'
);

create table organisations (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  status organisation_status not null,
  created_at timestamptz not null default now()
);

create table memberships (
  user_id uuid primary key references auth.users (id) on delete cascade,
  organisation_id uuid not null references organisations (id) on delete restrict,
  role user_role not null,
  created_at timestamptz not null default now()
);

create index memberships_org_idx on memberships (organisation_id);

alter table organisations enable row level security;
alter table memberships  enable row level security;

-- Helper: current user's membership (used by later RLS policies).
create or replace function app.current_membership()
returns table (organisation_id uuid, role user_role, org_status organisation_status)
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select m.organisation_id, m.role, o.status as org_status
  from memberships m
  join organisations o on o.id = m.organisation_id
  where m.user_id = auth.uid()
  limit 1;
$$;
