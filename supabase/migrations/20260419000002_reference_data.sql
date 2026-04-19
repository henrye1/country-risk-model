-- 20260419000002_reference_data.sql
-- Reference data: countries, country_segments, variables.

create type segment_code as enum ('HIGH', 'LOW', 'NODATA');
create type variable_category as enum ('Economic', 'Currency', 'Political', 'Business Risk', 'Risk', 'Finance');
create type direction_code as enum ('higher_better', 'higher_worse');

create table countries (
  iso3 char(3) primary key,
  name text not null,
  region text,
  created_at timestamptz not null default now()
);

create table country_segments (
  iso3 char(3) not null references countries (iso3) on delete cascade,
  as_of_year int not null,
  hdi_value numeric,
  segment segment_code not null,
  primary key (iso3, as_of_year)
);

create index country_segments_year_idx on country_segments (as_of_year);

create table variables (
  code text primary key,
  name text not null,
  category variable_category not null,
  direction direction_code not null,
  is_quantitative boolean not null,
  description text
);

alter table countries         enable row level security;
alter table country_segments  enable row level security;
alter table variables         enable row level security;
