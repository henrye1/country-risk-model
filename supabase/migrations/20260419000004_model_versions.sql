-- 20260419000004_model_versions.sql
-- Model versioning: one row per trained model (per segment), plus
-- coefficient / standardisation / bucket tables that reference it.

create type model_version_status as enum ('active', 'retired');

create table model_versions (
  id uuid primary key default gen_random_uuid(),
  segment segment_code not null,
  trained_at timestamptz not null default now(),
  trained_by uuid references auth.users (id),
  training_notes text,
  training_data_hash text not null,
  fit_metrics_json jsonb not null default '{}'::jsonb,
  status model_version_status not null default 'active'
);

create index model_versions_segment_status_idx on model_versions (segment, status);

create table model_coefficients (
  id uuid primary key default gen_random_uuid(),
  model_version_id uuid not null references model_versions (id) on delete cascade,
  variable_code text,
  coefficient numeric not null,
  is_intercept boolean not null default false,
  constraint coefficients_variable_or_intercept
    check ((is_intercept = true and variable_code is null)
        or (is_intercept = false and variable_code is not null))
);

create index model_coefficients_version_idx on model_coefficients (model_version_id);

create table model_standardisation (
  model_version_id uuid not null references model_versions (id) on delete cascade,
  variable_code text not null references variables (code),
  mean numeric not null,
  std numeric not null,
  primary key (model_version_id, variable_code)
);

create table model_buckets (
  id uuid primary key default gen_random_uuid(),
  model_version_id uuid not null references model_versions (id) on delete cascade,
  variable_code text not null references variables (code),
  bucket_order int not null,
  lower_bound numeric,         -- null = -infinity
  upper_bound numeric,         -- null = +infinity
  score numeric not null,
  constraint bucket_order_positive check (bucket_order >= 0)
);

create index model_buckets_version_variable_idx on model_buckets (model_version_id, variable_code, bucket_order);

-- RLS: internal-org only for all four tables.
alter table model_versions       enable row level security;
alter table model_coefficients   enable row level security;
alter table model_standardisation enable row level security;
alter table model_buckets        enable row level security;

create policy "model_versions: internal read"
on model_versions for select
using ((select org_status from app.current_membership()) = 'internal');

create policy "model_coefficients: internal read"
on model_coefficients for select
using ((select org_status from app.current_membership()) = 'internal');

create policy "model_standardisation: internal read"
on model_standardisation for select
using ((select org_status from app.current_membership()) = 'internal');

create policy "model_buckets: internal read"
on model_buckets for select
using ((select org_status from app.current_membership()) = 'internal');

-- Writes limited to service_role (backend admin path). No INSERT/UPDATE/DELETE policies for authenticated → blocked by RLS.
