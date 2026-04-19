# Plan 1 — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scaffold the Country Risk Model monorepo with a working FastAPI backend, React SPA frontend, Supabase project with auth + RLS, and reference tables (organisations, memberships, countries, variables, country_segments) seeded from the Excel prototype. End state: a developer (and you) can log in and see a role-aware landing page listing the 161 countries.

**Architecture:** Single repo with `backend/` (FastAPI), `frontend/` (Vite+React+TS), `prototype/` (archived xlsx), `docs/`, `supabase/migrations/`. Two Supabase cloud projects (`country-risk-dev` for development, `country-risk-prod` reserved for Plan 7 deployment). No local database — the Supabase CLI is linked to the `dev` project so migrations push there. pytest covers backend; Vitest covers frontend. Strict RLS from task zero.

**Tech Stack:** Python 3.11+ (FastAPI, pydantic, pydantic-settings, supabase-py, pytest), Node 20+ (Vite, React 18, TypeScript 5, Tailwind, shadcn/ui primitives, TanStack Query, Zod, Vitest), Supabase CLI (cloud-linked, no Docker), GitHub (source hosting), Render (deployment — used in Plan 7).

**Precondition:** Python 3.11+, Node 20+, `git` installed. Supabase CLI installed (`npm i -g supabase` or `scoop install supabase`). A GitHub account. A Render account. Two Supabase cloud projects created — see Task 2. No Docker required.

**Location assumption:** All paths in this plan are relative to the repo root `C:\Users\APR\OneDrive - Anchor Point Risk (Pty) Ltd\Desktop\VS_CODE_REPOSITORY\country-risk-model\`.

---

## File Structure After This Plan

```
country-risk-model/
├── .git/                                # initialised in Task 1
├── .gitignore
├── .env.example
├── README.md
├── prototype/
│   └── Country Prototype Original HDI with Ridge.xlsx    # moved from root
├── docs/
│   └── superpowers/
│       ├── specs/2026-04-19-country-risk-app-design.md
│       └── plans/2026-04-19-plan-1-foundation.md         # this file
├── supabase/
│   ├── config.toml                      # from `supabase init`
│   ├── migrations/
│   │   ├── 20260419000001_tenancy.sql
│   │   ├── 20260419000002_reference_data.sql
│   │   └── 20260419000003_rls.sql
│   └── seeds/
│       ├── countries.csv                # generated from xlsx
│       └── variables.csv                # generated from xlsx
├── backend/
│   ├── pyproject.toml
│   ├── .python-version
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                      # FastAPI app, CORS, routers, /health
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── settings.py              # env-driven config
│   │   │   ├── supabase.py              # client factories (anon + service)
│   │   │   ├── auth.py                  # JWT dep, CurrentUser
│   │   │   └── logging.py               # structured JSON logs
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── health.py
│   │   │   └── public.py                # /v1/countries, /v1/variables (read-only)
│   │   ├── schemas/
│   │   │   ├── __init__.py
│   │   │   ├── user.py                  # CurrentUser
│   │   │   ├── country.py               # CountryOut
│   │   │   └── variable.py              # VariableOut
│   │   └── repositories/
│   │       ├── __init__.py
│   │       └── reference.py             # read countries, variables from Supabase
│   ├── scripts/
│   │   └── extract_reference_from_xlsx.py  # regenerate seed CSVs
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py                  # test client + JWT fixtures
│       ├── test_health.py
│       ├── test_auth.py
│       └── test_public_countries.py
├── frontend/
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── tailwind.config.ts
│   ├── postcss.config.js
│   ├── index.html
│   ├── .env.example
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── routes.tsx
│   │   ├── index.css                    # Tailwind directives
│   │   ├── lib/
│   │   │   ├── supabase.ts
│   │   │   └── api.ts                   # typed fetcher with JWT
│   │   ├── features/
│   │   │   ├── auth/
│   │   │   │   ├── AuthProvider.tsx
│   │   │   │   ├── LoginPage.tsx
│   │   │   │   └── RequireAuth.tsx
│   │   │   └── countries/
│   │   │       └── CountryListPage.tsx
│   │   └── components/
│   │       └── AppShell.tsx             # nav + layout
│   └── tests/
│       ├── setup.ts
│       ├── LoginPage.test.tsx
│       └── CountryListPage.test.tsx
└── .github/
    └── workflows/
        └── ci.yml                       # lint + test on PR
```

---

## Task 1: Repo skeleton, git init, move prototype

**Files:**
- Create: `.gitignore`
- Create: `README.md`
- Create: `.env.example`
- Move: `Country Prototype Original HDI with Ridge.xlsx` → `prototype/Country Prototype Original HDI with Ridge.xlsx`

- [ ] **Step 1: Initialise git + set identity**

```bash
cd "C:/Users/APR/OneDrive - Anchor Point Risk (Pty) Ltd/Desktop/VS_CODE_REPOSITORY/country-risk-model/"
git init -b main
```

Expected: `Initialized empty Git repository in .../country-risk-model/.git/`

- [ ] **Step 2: Create `.gitignore`**

```
# Python
__pycache__/
*.py[cod]
*.egg-info/
.venv/
.pytest_cache/
.ruff_cache/
.mypy_cache/
htmlcov/
.coverage

# Node
node_modules/
dist/
.vite/
coverage/

# Env
.env
.env.local
.env.*.local

# OS / IDE
.DS_Store
Thumbs.db
.idea/
.vscode/*
!.vscode/settings.json
!.vscode/extensions.json

# Supabase
supabase/.branches/
supabase/.temp/

# Logs
*.log
```

- [ ] **Step 3: Create `README.md`**

```markdown
# Country Risk Model

Web application that converts Anchor Point Risk's Excel country-risk prototype into a versioned, auditable scoring system. Scores feed the firm's PD and LGD rating models via a REST API.

See `docs/superpowers/specs/2026-04-19-country-risk-app-design.md` for the design.
See `docs/superpowers/plans/` for implementation plans.

## Stack
- Backend: FastAPI + Python 3.11+
- Frontend: React + Vite + TypeScript
- Database / Auth: Supabase (Postgres + RLS)

## Local setup
1. Install Python 3.11+, Node 20+, and Supabase CLI.
2. Create two Supabase cloud projects (`country-risk-dev`, `country-risk-prod`).
3. Copy `.env.example` to `.env` and fill in the `dev` project's values.
4. `cd backend && pip install -e ".[dev]" && pytest`
5. `cd frontend && npm install && npm test`
6. `supabase link --project-ref=<dev-ref>` then `supabase db push` to apply migrations to the dev project.

## Structure
- `prototype/` — original Excel file (regression-test source of truth)
- `backend/` — FastAPI service
- `frontend/` — React SPA
- `supabase/migrations/` — SQL migrations, one file per logical change
- `docs/superpowers/` — specs and implementation plans
```

- [ ] **Step 4: Create `.env.example`**

```
# Supabase (shared; values come from your Supabase project's Settings → API)
SUPABASE_URL=https://YOUR-PROJECT.supabase.co
SUPABASE_ANON_KEY=eyJhbGciOi...
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOi...
SUPABASE_JWT_SECRET=your-jwt-secret

# Backend
BACKEND_PORT=8000
LOG_LEVEL=INFO
CORS_ORIGINS=http://localhost:5173

# Frontend (values mirror Supabase, prefixed VITE_)
VITE_SUPABASE_URL=https://YOUR-PROJECT.supabase.co
VITE_SUPABASE_ANON_KEY=eyJhbGciOi...
VITE_API_BASE_URL=http://localhost:8000
```

- [ ] **Step 5: Move the prototype xlsx into `prototype/`**

```bash
mkdir -p prototype
mv "Country Prototype Original HDI with Ridge.xlsx" prototype/
```

- [ ] **Step 6: First commit**

```bash
git add .gitignore README.md .env.example prototype/ docs/
git commit -m "chore: repo skeleton, gitignore, prototype archive"
```

Expected: one commit listing those files.

- [ ] **Step 7: Create GitHub repo and push**

Create an empty private repo on GitHub at `https://github.com/new` (suggested name: `country-risk-model`). **Do not** initialise it with a README or `.gitignore` — we've already added those.

Then wire up the remote and push:

```bash
git remote add origin https://github.com/<your-username>/country-risk-model.git
git push -u origin main
```

Expected: push completes; GitHub now shows your repo with the skeleton files.

From this point on, every commit from subsequent tasks can be pushed with `git push`. Open GitHub and confirm you can see the commit.

---

## Task 2: Create Supabase cloud projects and link CLI

**Files:**
- Create: `supabase/config.toml` (via `supabase init`)

- [ ] **Step 1: Create two Supabase cloud projects**

Go to `https://supabase.com/dashboard` and click **"New project"** twice:

1. **`country-risk-dev`** — used for local development. Choose a strong DB password and record it.
2. **`country-risk-prod`** — used by Plan 7 for production deployment. For now, just create it; don't configure anything inside it.

For each project, go to **Settings → API** and note down:
- Project URL (e.g. `https://abcdxyz.supabase.co`)
- `anon` / `public` key
- `service_role` / `secret` key

Also: **Settings → API → JWT Settings** → note the **JWT Secret**.

- [ ] **Step 2: Fill in `.env` at the repo root**

Copy `.env.example` to `.env` and populate it with the **dev** project's values:

```bash
cp .env.example .env
```

Edit `.env`:
```
SUPABASE_URL=https://<dev-project-ref>.supabase.co
SUPABASE_ANON_KEY=<dev anon key>
SUPABASE_SERVICE_ROLE_KEY=<dev service role key>
SUPABASE_JWT_SECRET=<dev JWT secret>

BACKEND_PORT=8000
LOG_LEVEL=INFO
CORS_ORIGINS=http://localhost:5173

VITE_SUPABASE_URL=https://<dev-project-ref>.supabase.co
VITE_SUPABASE_ANON_KEY=<dev anon key>
VITE_API_BASE_URL=http://localhost:8000
```

- [ ] **Step 3: Initialise the Supabase config folder**

```bash
supabase init
```

Expected: `Finished supabase init.` A `supabase/` directory appears with `config.toml` and empty `migrations/` folder.

- [ ] **Step 4: Log in and link CLI to the dev project**

```bash
supabase login
```

This opens a browser to generate a CLI access token. Paste it back when prompted.

```bash
supabase link --project-ref=<dev-project-ref>
```

Where `<dev-project-ref>` is the short code in the dev project's URL (the `abcdxyz` part of `abcdxyz.supabase.co`). The CLI will prompt for the dev project's DB password (from Step 1).

Expected: `Finished supabase link.`

- [ ] **Step 5: Verify Studio is reachable**

Visit `https://supabase.com/dashboard/project/<dev-project-ref>` in a browser. You should see the empty dev project in Supabase Studio. No tables yet.

- [ ] **Step 6: Commit the supabase scaffold**

```bash
git add supabase/config.toml supabase/
git commit -m "chore: supabase init + link CLI to country-risk-dev"
```

Do **not** commit `.env` — `.gitignore` already excludes it.

---

## Task 3: Migration 1 — tenancy tables + RLS skeleton

**Files:**
- Create: `supabase/migrations/20260419000001_tenancy.sql`

- [ ] **Step 1: Write the migration**

```sql
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
```

- [ ] **Step 2: Apply the migration**

```bash
supabase db push --linked
```

Expected: `Applying migration 20260419000001_tenancy.sql... Finished.`

- [ ] **Step 3: Verify in Studio**

In the cloud dev project's Studio (`https://supabase.com/dashboard/project/<dev-ref>`), open **Database → Tables**: `organisations` and `memberships` should exist, both with RLS enabled (padlock icon).

- [ ] **Step 4: Commit**

```bash
git add supabase/migrations/20260419000001_tenancy.sql
git commit -m "feat(db): tenancy tables (organisations, memberships) with role enum"
```

---

## Task 4: Migration 2 — reference data tables

**Files:**
- Create: `supabase/migrations/20260419000002_reference_data.sql`

- [ ] **Step 1: Write the migration**

```sql
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
```

- [ ] **Step 2: Apply the migration**

```bash
supabase db push --linked
```

Expected: migration applied; three new tables visible in Studio.

- [ ] **Step 3: Commit**

```bash
git add supabase/migrations/20260419000002_reference_data.sql
git commit -m "feat(db): reference tables (countries, country_segments, variables)"
```

---

## Task 5: Migration 3 — RLS policies

**Files:**
- Create: `supabase/migrations/20260419000003_rls.sql`

- [ ] **Step 1: Write the migration**

```sql
-- 20260419000003_rls.sql
-- RLS policies for tenancy + reference tables.

-- organisations: members can see their own org; internal can see all
create policy "orgs: own or internal"
on organisations for select
using (
  id = (select organisation_id from app.current_membership())
  or (select org_status from app.current_membership()) = 'internal'
);

-- memberships: each user can see only their own row; internal can see all
create policy "memberships: own or internal"
on memberships for select
using (
  user_id = auth.uid()
  or (select org_status from app.current_membership()) = 'internal'
);

-- reference data: any authenticated user can read
create policy "countries: authenticated read"
on countries for select
to authenticated
using (true);

create policy "country_segments: authenticated read"
on country_segments for select
to authenticated
using (true);

create policy "variables: authenticated read"
on variables for select
to authenticated
using (true);

-- Writes to reference tables restricted to service_role (backend-only seeding and future migrations).
-- No INSERT/UPDATE/DELETE policies for authenticated users → RLS blocks them by default.
```

- [ ] **Step 2: Apply the migration**

```bash
supabase db push --linked
```

- [ ] **Step 3: Commit**

```bash
git add supabase/migrations/20260419000003_rls.sql
git commit -m "feat(db): RLS policies — own-org reads + authenticated reference reads"
```

---

## Task 6: Extract seed CSVs from the Excel prototype

**Files:**
- Create: `backend/scripts/extract_reference_from_xlsx.py`
- Create: `supabase/seeds/countries.csv`
- Create: `supabase/seeds/variables.csv`

- [ ] **Step 1: Write the extractor script**

Create `backend/scripts/extract_reference_from_xlsx.py`:

```python
"""Extract reference data (countries + variables) from the Excel prototype into seed CSVs.

Re-run whenever the prototype is updated. Outputs:
  supabase/seeds/countries.csv — iso3, name, region, as_of_year, hdi_value, segment
  supabase/seeds/variables.csv — code, name, category, direction, is_quantitative, description
"""
from __future__ import annotations
import csv
from pathlib import Path
from openpyxl import load_workbook

REPO_ROOT = Path(__file__).resolve().parents[2]
XLSX = REPO_ROOT / "prototype" / "Country Prototype Original HDI with Ridge.xlsx"
SEEDS_DIR = REPO_ROOT / "supabase" / "seeds"

REGION_MAP = {
    "AFRICA": "AFRICA",
    "EMERGING MARKET NON-AFRICA": "EMERGING_NON_AFRICA",
    "DEVELOPED MARKET": "DEVELOPED",
}

HDI_TO_VALUE = {
    "VERY HIGH HUMAN DEVELOPMENT": 0.9,
    "HIGH HUMAN DEVELOPMENT": 0.75,
    "MEDIUM HUMAN DEVELOPMENT": 0.6,
    "LOW HUMAN DEVELOPMENT": 0.45,
}

# Built from the Excel "High Segment" driver list (column 'Low mapping' at col I)
# plus the "Variable Definitions" sheet. See spec §4.2.
VARIABLES = [
    # code,                 name,                                 category,         direction,        is_quant, description
    ("dcpi_5_adj",          "Inflation 5 year average",           "Economic",       "higher_worse",   True,     "Average CPI % change over 5 years."),
    ("nom_rir_vol",         "Nominal Interest Rate Volatility",   "Economic",       "higher_worse",   True,     "Volatility of nominal interest rates."),
    ("gdp_capita",          "GDP per Capita",                     "Economic",       "higher_better",  True,     "GDP per head (US$)."),
    ("growth_vol",          "Growth Volatility",                  "Economic",       "higher_worse",   True,     "Stdev of Real GDP % change over 5 years."),
    ("macro_var",           "Macroeconomic",                      "Economic",       "higher_better",  False,    "Qualitative macroeconomic stability score."),
    ("atf",                 "Access to Finance",                  "Currency",       "higher_better",  False,    "Qualitative access-to-finance score."),
    ("dt",                  "Debt Trend",                         "Currency",       "higher_worse",   True,     "3-year trend in foreign debt to GDP."),
    ("fdg_3yr",             "Foreign Debt to GDP 3 year average", "Currency",       "higher_worse",   True,     "Average foreign debt / GDP over 3 years."),
    ("cof",                 "Cost of Funds",                      "Finance",        "higher_worse",   True,     "Money market interest rate (%)."),
    ("pr",                  "Political Risk Environment",         "Political",      "higher_better",  False,    "Qualitative political risk score."),
    ("rol",                 "Rule of Law",                        "Business Risk",  "higher_better",  False,    "World Governance Indicator: Rule of Law."),
    ("db",                  "Doing Business",                     "Business Risk",  "higher_better",  False,    "World Bank Doing Business qualitative score."),
    ("sr",                  "Security Risk",                      "Risk",           "higher_better",  False,    "Global Insights security risk score."),
    ("debt_service_ratio",  "Debt Service Ratio 1 year",          "Currency",       "higher_worse",   True,     "Debt service due as % of exports + remittances."),
]


def main() -> None:
    SEEDS_DIR.mkdir(parents=True, exist_ok=True)
    wb = load_workbook(XLSX, data_only=True)

    # --- countries ---
    country_sheet = wb["Country List"]
    # Work out which analytical segment each country belongs to by scanning the three columns
    # (LOW, HIGH, No Data) under their headers. Those are sorted name lists.
    rows = list(country_sheet.iter_rows(min_row=2, values_only=True))

    low_names = {r[5] for r in rows if r[5]}
    high_names = {r[6] for r in rows if r[6]}
    nodata_names = {r[7] for r in rows if r[7]}

    country_rows = []
    for r in rows:
        name, iso3, hdi_label, em_dm = r[0], r[1], r[2], r[3]
        if not (name and iso3):
            continue
        if name in high_names:
            segment = "HIGH"
        elif name in low_names:
            segment = "LOW"
        elif name in nodata_names:
            segment = "NODATA"
        else:
            # Fall back by HDI band: MEDIUM → LOW per the prototype's grouping
            segment = "NODATA"
        country_rows.append({
            "iso3": iso3.strip(),
            "name": name.strip(),
            "region": REGION_MAP.get((em_dm or "").strip(), "UNKNOWN"),
            "as_of_year": 2011,  # prototype baseline year per Variable Definitions sheet
            "hdi_value": HDI_TO_VALUE.get((hdi_label or "").strip(), None),
            "segment": segment,
        })

    countries_csv = SEEDS_DIR / "countries.csv"
    with countries_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["iso3", "name", "region", "as_of_year", "hdi_value", "segment"])
        writer.writeheader()
        writer.writerows(country_rows)
    print(f"Wrote {len(country_rows)} countries -> {countries_csv}")

    # --- variables ---
    variables_csv = SEEDS_DIR / "variables.csv"
    with variables_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["code", "name", "category", "direction", "is_quantitative", "description"])
        for v in VARIABLES:
            writer.writerow(list(v))
    print(f"Wrote {len(VARIABLES)} variables -> {variables_csv}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Install openpyxl temporarily and run it**

```bash
pip install openpyxl
python backend/scripts/extract_reference_from_xlsx.py
```

Expected (row count should be ~160; the prototype lists between 158 and 162 countries depending on trailing blanks):
```
Wrote 160 countries -> .../supabase/seeds/countries.csv
Wrote 14 variables -> .../supabase/seeds/variables.csv
```

Sanity-check the output CSV has one row per country and no obvious junk; if any country is missing its segment classification or the region is "UNKNOWN" unexpectedly, adjust `REGION_MAP` or the segment-detection logic in the script and rerun.

- [ ] **Step 3: Commit**

```bash
git add backend/scripts/extract_reference_from_xlsx.py supabase/seeds/
git commit -m "feat(seeds): extract reference data from Excel prototype"
```

---

## Task 7: Load seed data into local Supabase

**Files:**
- Create: `supabase/seed.sql` (or append to existing — `supabase init` creates it empty)

- [ ] **Step 1: Write `supabase/seed.sql`**

```sql
-- Seed file: runs automatically after migrations on `supabase db reset`.
-- Reference data only. Tenancy seed is in Task 8.

-- variables
\copy variables(code, name, category, direction, is_quantitative, description) from 'supabase/seeds/variables.csv' with (format csv, header true);

-- countries (split across the three tables)
create temp table _raw_countries (
  iso3 text, name text, region text, as_of_year int, hdi_value numeric, segment text
) on commit drop;

\copy _raw_countries from 'supabase/seeds/countries.csv' with (format csv, header true);

insert into countries (iso3, name, region)
select iso3, name, region from _raw_countries
on conflict (iso3) do nothing;

insert into country_segments (iso3, as_of_year, hdi_value, segment)
select iso3, as_of_year, hdi_value, segment::segment_code from _raw_countries
on conflict (iso3, as_of_year) do nothing;
```

- [ ] **Step 2: Reset the dev Supabase DB to apply migrations + seed together**

> ⚠️ **Destructive.** `supabase db reset --linked` wipes the **linked cloud dev project** and re-applies migrations + seed. Only run this against `country-risk-dev`. Double-check your link target first: `supabase projects list` should show the dev project as linked (look for the green check).

```bash
supabase db reset --linked
```

When prompted, confirm by typing the project ref. Expected: migrations run, then seed executes, then `Finished supabase db reset.` Supabase Studio (cloud) now shows ~160 rows in `countries` and 14 rows in `variables`.

- [ ] **Step 3: Verify count via Studio (or psql)**

Easiest — in the cloud Studio SQL editor:
```sql
select count(*) from countries;
```

Or from the CLI (the printed URL is safe to use with psql):
```bash
supabase db url --linked
# psql "<url>" -c "select count(*) from countries;"
```

Expected: around `160` (matches your CSV row count).

- [ ] **Step 4: Commit**

```bash
git add supabase/seed.sql
git commit -m "feat(seeds): load countries + variables + country_segments on db reset"
```

---

## Task 8: Seed one internal organisation + one test user (dev only)

**Files:**
- Modify: `supabase/seed.sql` (append dev-only section)

- [ ] **Step 1: Append tenancy seed to `supabase/seed.sql`**

Append at the end:

```sql
-- Dev-only tenancy seed. Creates one internal org and one client org.
-- Users must be created via `supabase auth` commands or the Studio UI; their memberships are added here by email lookup.

insert into organisations (id, name, status)
values
  ('00000000-0000-0000-0000-0000000000a1', 'Anchor Point Risk (internal)', 'internal'),
  ('00000000-0000-0000-0000-0000000000b1', 'Sample Client Bank',          'client'),
  ('00000000-0000-0000-0000-0000000000c1', 'System Service Accounts',     'system')
on conflict (id) do nothing;
```

- [ ] **Step 2: Reset DB**

```bash
supabase db reset --linked
```

Expected: three organisations visible in Studio.

- [ ] **Step 3: Create two test users via Studio**

In Studio → Authentication → Users → "Add user":
- `owner@anchorpointrisk.local` / any strong password → note the user UUID
- `client@sampleclient.local` / any strong password → note the user UUID

- [ ] **Step 4: Add memberships via Studio SQL editor**

Paste into Studio SQL editor (replace UUIDs with the ones you noted):

```sql
insert into memberships (user_id, organisation_id, role) values
  ('<owner-user-uuid>', '00000000-0000-0000-0000-0000000000a1', 'internal_owner'),
  ('<client-user-uuid>', '00000000-0000-0000-0000-0000000000b1', 'client_admin')
on conflict (user_id) do update set role = excluded.role, organisation_id = excluded.organisation_id;
```

Expected: two rows inserted.

- [ ] **Step 5: Commit**

```bash
git add supabase/seed.sql
git commit -m "chore(seeds): dev tenancy seed (orgs only; users created manually in Studio)"
```

---

## Task 9: Backend — pyproject.toml and dir layout

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/.python-version`
- Create: `backend/app/__init__.py`
- Create: `backend/app/api/__init__.py`
- Create: `backend/app/core/__init__.py`
- Create: `backend/app/schemas/__init__.py`
- Create: `backend/app/repositories/__init__.py`
- Create: `backend/tests/__init__.py`

- [ ] **Step 1: Create `backend/.python-version`**

```
3.11
```

- [ ] **Step 2: Create `backend/pyproject.toml`**

```toml
[project]
name = "country-risk-backend"
version = "0.1.0"
description = "Country Risk Model backend"
requires-python = ">=3.11,<3.13"
dependencies = [
  "fastapi>=0.110",
  "uvicorn[standard]>=0.27",
  "pydantic>=2.6",
  "pydantic-settings>=2.2",
  "supabase>=2.4",
  "httpx>=0.27",
  "python-jose[cryptography]>=3.3",
  "structlog>=24.1",
  "openpyxl>=3.1",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.0",
  "pytest-asyncio>=0.23",
  "pytest-cov>=4.1",
  "httpx>=0.27",
  "ruff>=0.3",
  "mypy>=1.8",
  "respx>=0.20",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["app"]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
asyncio_mode = "auto"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM"]

[tool.mypy]
python_version = "3.11"
strict = true
ignore_missing_imports = true
```

- [ ] **Step 3: Create empty `__init__.py` files**

```bash
touch backend/app/__init__.py backend/app/api/__init__.py backend/app/core/__init__.py backend/app/schemas/__init__.py backend/app/repositories/__init__.py backend/tests/__init__.py
```

- [ ] **Step 4: Create and activate a venv, install deps**

```bash
cd backend
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash
pip install -e ".[dev]"
cd ..
```

Expected: `Successfully installed fastapi-0.... pytest-8...`

- [ ] **Step 5: Commit**

```bash
git add backend/pyproject.toml backend/.python-version backend/app backend/tests
git commit -m "chore(backend): pyproject + empty package layout"
```

---

## Task 10: Backend — settings & structured logging

**Files:**
- Create: `backend/app/core/settings.py`
- Create: `backend/app/core/logging.py`
- Create: `backend/tests/test_settings.py`

- [ ] **Step 1: Write failing test `backend/tests/test_settings.py`**

```python
from app.core.settings import Settings


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "secret")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173,http://foo.test")

    s = Settings()

    assert s.supabase_url == "https://x.supabase.co"
    assert s.supabase_anon_key == "anon"
    assert s.supabase_service_role_key == "service"
    assert s.supabase_jwt_secret == "secret"
    assert s.cors_origins == ["http://localhost:5173", "http://foo.test"]
    assert s.log_level == "INFO"
```

- [ ] **Step 2: Run the test, confirm it fails**

```bash
cd backend && .venv/Scripts/python -m pytest tests/test_settings.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.core.settings'`

- [ ] **Step 3: Implement `backend/app/core/settings.py`**

```python
from __future__ import annotations
from functools import lru_cache
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", env_file_encoding="utf-8", extra="ignore")

    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    supabase_jwt_secret: str

    backend_port: int = 8000
    log_level: str = "INFO"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_csv(cls, v):
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Run the test — should pass**

```bash
cd backend && .venv/Scripts/python -m pytest tests/test_settings.py -v
```

Expected: `1 passed`

- [ ] **Step 5: Implement `backend/app/core/logging.py`**

```python
from __future__ import annotations
import logging
import sys
import structlog
from app.core.settings import get_settings


def configure_logging() -> None:
    settings = get_settings()
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/settings.py backend/app/core/logging.py backend/tests/test_settings.py
git commit -m "feat(backend): settings (env) and structured JSON logging"
```

---

## Task 11: Backend — FastAPI app + /health endpoint (TDD)

**Files:**
- Create: `backend/app/api/health.py`
- Create: `backend/app/main.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_health.py`

- [ ] **Step 1: Write `backend/tests/conftest.py`**

```python
from __future__ import annotations
import os
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _set_env(monkeypatch):
    # Default env for all tests; individual tests can override.
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-jwt-secret")

    # Clear cached settings so env changes take effect.
    from app.core.settings import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client() -> TestClient:
    from app.main import create_app
    return TestClient(create_app())
```

- [ ] **Step 2: Write failing test `backend/tests/test_health.py`**

```python
def test_health_returns_ok(client):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": "0.1.0"}
```

- [ ] **Step 3: Run, confirm it fails**

```bash
cd backend && .venv/Scripts/python -m pytest tests/test_health.py -v
```

Expected: `ImportError: cannot import name 'create_app'`

- [ ] **Step 4: Implement `backend/app/api/health.py`**

```python
from fastapi import APIRouter

router = APIRouter(prefix="/v1", tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.1.0"}
```

- [ ] **Step 5: Implement `backend/app/main.py`**

```python
from __future__ import annotations
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health
from app.core.logging import configure_logging
from app.core.settings import get_settings


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()

    app = FastAPI(title="Country Risk Model API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    return app


app = create_app()
```

- [ ] **Step 6: Run tests — should pass**

```bash
cd backend && .venv/Scripts/python -m pytest tests/ -v
```

Expected: `2 passed`

- [ ] **Step 7: Boot the server manually to sanity-check**

```bash
cd backend && .venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
```

In another terminal:

```bash
curl http://localhost:8000/v1/health
```

Expected: `{"status":"ok","version":"0.1.0"}`. Stop the server (Ctrl-C).

- [ ] **Step 8: Commit**

```bash
git add backend/app/main.py backend/app/api/health.py backend/tests/conftest.py backend/tests/test_health.py
git commit -m "feat(backend): FastAPI app + /v1/health (TDD)"
```

---

## Task 12: Backend — JWT auth dependency (TDD)

**Files:**
- Create: `backend/app/schemas/user.py`
- Create: `backend/app/core/auth.py`
- Create: `backend/tests/test_auth.py`

- [ ] **Step 1: Write `backend/app/schemas/user.py`**

```python
from __future__ import annotations
from pydantic import BaseModel
from uuid import UUID


class CurrentUser(BaseModel):
    user_id: UUID
    email: str | None = None
    raw_jwt: str
```

- [ ] **Step 2: Write failing test `backend/tests/test_auth.py`**

```python
from __future__ import annotations
import time
import pytest
from jose import jwt
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

JWT_SECRET = "test-jwt-secret"


def _token(user_id: str = "11111111-1111-1111-1111-111111111111", email: str = "u@example.com") -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
        "aud": "authenticated",
        "role": "authenticated",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


@pytest.fixture
def app_with_protected() -> FastAPI:
    from app.core.auth import get_current_user
    from app.schemas.user import CurrentUser

    app = FastAPI()

    @app.get("/me")
    def me(user: CurrentUser = Depends(get_current_user)) -> dict:
        return {"user_id": str(user.user_id), "email": user.email}

    return app


def test_missing_token_returns_401(app_with_protected):
    c = TestClient(app_with_protected)
    r = c.get("/me")
    assert r.status_code == 401


def test_invalid_token_returns_401(app_with_protected):
    c = TestClient(app_with_protected)
    r = c.get("/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401


def test_valid_token_returns_user(app_with_protected):
    c = TestClient(app_with_protected)
    r = c.get("/me", headers={"Authorization": f"Bearer {_token()}"})
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == "11111111-1111-1111-1111-111111111111"
    assert body["email"] == "u@example.com"
```

- [ ] **Step 3: Run — confirm fail**

```bash
cd backend && .venv/Scripts/python -m pytest tests/test_auth.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.core.auth'`

- [ ] **Step 4: Implement `backend/app/core/auth.py`**

```python
from __future__ import annotations
from uuid import UUID
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.core.settings import Settings, get_settings
from app.schemas.user import CurrentUser

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    if creds is None or not creds.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")
    try:
        payload = jwt.decode(
            creds.credentials,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token") from exc

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token missing sub claim")

    return CurrentUser(user_id=UUID(sub), email=payload.get("email"), raw_jwt=creds.credentials)
```

- [ ] **Step 5: Run — should pass**

```bash
cd backend && .venv/Scripts/python -m pytest tests/test_auth.py -v
```

Expected: `3 passed`

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/user.py backend/app/core/auth.py backend/tests/test_auth.py
git commit -m "feat(backend): JWT auth dependency (Supabase HS256)"
```

---

## Task 13: Backend — Supabase client factory

**Files:**
- Create: `backend/app/core/supabase.py`
- Create: `backend/tests/test_supabase_factory.py`

- [ ] **Step 1: Write failing test `backend/tests/test_supabase_factory.py`**

```python
def test_anon_client_uses_anon_key():
    from app.core.supabase import anon_client
    c = anon_client()
    # supabase-py stores the key on .postgrest.auth_token or .auth; simplest assertion is that it exists.
    assert c is not None


def test_service_client_uses_service_key():
    from app.core.supabase import service_client
    c = service_client()
    assert c is not None


def test_user_client_injects_jwt():
    from app.core.supabase import user_client
    c = user_client("eyJ.fake.jwt")
    assert c is not None
```

- [ ] **Step 2: Run — confirm fail**

```bash
cd backend && .venv/Scripts/python -m pytest tests/test_supabase_factory.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.core.supabase'`

- [ ] **Step 3: Implement `backend/app/core/supabase.py`**

```python
from __future__ import annotations
from functools import lru_cache
from supabase import Client, create_client
from supabase.client import ClientOptions

from app.core.settings import get_settings


@lru_cache
def anon_client() -> Client:
    s = get_settings()
    return create_client(s.supabase_url, s.supabase_anon_key)


@lru_cache
def service_client() -> Client:
    s = get_settings()
    # Service-role bypasses RLS. Use only for internal admin / fan-out work.
    return create_client(s.supabase_url, s.supabase_service_role_key)


def user_client(jwt: str) -> Client:
    """Return a client that executes queries as the given user (respects RLS)."""
    s = get_settings()
    options = ClientOptions(headers={"Authorization": f"Bearer {jwt}"})
    return create_client(s.supabase_url, s.supabase_anon_key, options=options)
```

- [ ] **Step 4: Run — should pass**

```bash
cd backend && .venv/Scripts/python -m pytest tests/test_supabase_factory.py -v
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/supabase.py backend/tests/test_supabase_factory.py
git commit -m "feat(backend): supabase client factories (anon / service / user-scoped)"
```

---

## Task 14: Backend — schemas and repositories for reference data

**Files:**
- Create: `backend/app/schemas/country.py`
- Create: `backend/app/schemas/variable.py`
- Create: `backend/app/repositories/reference.py`

- [ ] **Step 1: Create `backend/app/schemas/country.py`**

```python
from __future__ import annotations
from pydantic import BaseModel


class CountryOut(BaseModel):
    iso3: str
    name: str
    region: str | None = None
```

- [ ] **Step 2: Create `backend/app/schemas/variable.py`**

```python
from __future__ import annotations
from pydantic import BaseModel


class VariableOut(BaseModel):
    code: str
    name: str
    category: str
    direction: str
    is_quantitative: bool
    description: str | None = None
```

- [ ] **Step 3: Create `backend/app/repositories/reference.py`**

```python
from __future__ import annotations
from supabase import Client

from app.schemas.country import CountryOut
from app.schemas.variable import VariableOut


class ReferenceRepository:
    """Thin wrapper over Supabase client for reading reference tables."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def list_countries(self) -> list[CountryOut]:
        resp = self._client.table("countries").select("iso3, name, region").order("name").execute()
        return [CountryOut(**row) for row in resp.data]

    def list_variables(self) -> list[VariableOut]:
        resp = (
            self._client.table("variables")
            .select("code, name, category, direction, is_quantitative, description")
            .order("code")
            .execute()
        )
        return [VariableOut(**row) for row in resp.data]
```

- [ ] **Step 4: Commit (no tests yet — these hit a real DB; see next task)**

```bash
git add backend/app/schemas/country.py backend/app/schemas/variable.py backend/app/repositories/reference.py
git commit -m "feat(backend): reference schemas + repository"
```

---

## Task 15: Backend — /v1/countries and /v1/variables endpoints (integration test)

**Files:**
- Create: `backend/app/api/public.py`
- Modify: `backend/app/main.py` — register router
- Create: `backend/tests/test_public_countries.py`

- [ ] **Step 1: Implement `backend/app/api/public.py`**

```python
from __future__ import annotations
from fastapi import APIRouter, Depends

from app.core.auth import get_current_user
from app.core.supabase import user_client
from app.repositories.reference import ReferenceRepository
from app.schemas.country import CountryOut
from app.schemas.user import CurrentUser
from app.schemas.variable import VariableOut

router = APIRouter(prefix="/v1", tags=["public"])


@router.get("/countries", response_model=list[CountryOut])
def list_countries(user: CurrentUser = Depends(get_current_user)) -> list[CountryOut]:
    repo = ReferenceRepository(user_client(user.raw_jwt))
    return repo.list_countries()


@router.get("/variables", response_model=list[VariableOut])
def list_variables(user: CurrentUser = Depends(get_current_user)) -> list[VariableOut]:
    repo = ReferenceRepository(user_client(user.raw_jwt))
    return repo.list_variables()
```

- [ ] **Step 2: Register router in `backend/app/main.py`**

Change:

```python
from app.api import health
```

To:

```python
from app.api import health, public
```

And below `app.include_router(health.router)` add:

```python
    app.include_router(public.router)
```

- [ ] **Step 3: Write integration test `backend/tests/test_public_countries.py`**

This test talks to the **cloud `country-risk-dev` Supabase project** directly. It requires migrations to have been applied and the Task 8 tenancy seed to be in place. It's marked `@pytest.mark.integration` so the default unit-test run skips it.

```python
from __future__ import annotations
import os
import time
import pytest
from jose import jwt
from fastapi.testclient import TestClient


def _dev_token(user_id: str, jwt_secret: str) -> str:
    payload = {
        "sub": user_id,
        "email": "tester@example.com",
        "aud": "authenticated",
        "role": "authenticated",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    return jwt.encode(payload, jwt_secret, algorithm="HS256")


def _env_or_skip(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        pytest.skip(f"Integration test requires env var {name}")
    return v


@pytest.mark.integration
def test_list_countries_requires_auth(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", _env_or_skip("SUPABASE_URL_DEV"))
    monkeypatch.setenv("SUPABASE_ANON_KEY", _env_or_skip("SUPABASE_ANON_KEY_DEV"))
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", _env_or_skip("SUPABASE_SERVICE_ROLE_KEY_DEV"))
    monkeypatch.setenv("SUPABASE_JWT_SECRET", _env_or_skip("SUPABASE_JWT_SECRET_DEV"))

    from app.core.settings import get_settings
    get_settings.cache_clear()
    from app.main import create_app
    c = TestClient(create_app())

    r = c.get("/v1/countries")
    assert r.status_code == 401


@pytest.mark.integration
def test_list_countries_returns_full_list(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", _env_or_skip("SUPABASE_URL_DEV"))
    monkeypatch.setenv("SUPABASE_ANON_KEY", _env_or_skip("SUPABASE_ANON_KEY_DEV"))
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", _env_or_skip("SUPABASE_SERVICE_ROLE_KEY_DEV"))
    monkeypatch.setenv("SUPABASE_JWT_SECRET", _env_or_skip("SUPABASE_JWT_SECRET_DEV"))

    from app.core.settings import get_settings
    get_settings.cache_clear()
    from app.main import create_app
    c = TestClient(create_app())

    token = _dev_token(
        _env_or_skip("TEST_OWNER_USER_ID"),
        _env_or_skip("SUPABASE_JWT_SECRET_DEV"),
    )
    r = c.get("/v1/countries", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    # Full country list from the prototype; the CSV you generated in Task 6 is the source of truth.
    assert len(r.json()) >= 150
```

- [ ] **Step 4: Update `backend/pyproject.toml` `[tool.pytest.ini_options]`**

Add a marker so unit tests can skip integration tests by default:

```toml
[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
asyncio_mode = "auto"
markers = ["integration: requires a linked Supabase cloud dev project"]
addopts = "-m 'not integration'"
```

- [ ] **Step 5: Run unit tests — should still pass (integration skipped)**

```bash
cd backend && .venv/Scripts/python -m pytest -v
```

Expected: `X passed, 2 deselected`

- [ ] **Step 6: Run integration tests manually against the dev cloud project**

Export the dev project's values (from your `.env` and the test user UUID from Task 8):

```bash
export SUPABASE_URL_DEV="https://<dev-ref>.supabase.co"
export SUPABASE_ANON_KEY_DEV="<from .env>"
export SUPABASE_SERVICE_ROLE_KEY_DEV="<from .env>"
export SUPABASE_JWT_SECRET_DEV="<from .env>"
export TEST_OWNER_USER_ID="<uuid from Task 8>"
cd backend && .venv/Scripts/python -m pytest -m integration -v
```

Expected: `2 passed`

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/public.py backend/app/main.py backend/tests/test_public_countries.py backend/pyproject.toml
git commit -m "feat(backend): /v1/countries and /v1/variables read endpoints"
```

---

## Task 16: Frontend — Vite + React + TS scaffold

**Files:**
- Create (via Vite): `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/index.html`, `frontend/src/main.tsx`, `frontend/src/App.tsx`

- [ ] **Step 1: Scaffold the app**

```bash
cd "C:/Users/APR/OneDrive - Anchor Point Risk (Pty) Ltd/Desktop/VS_CODE_REPOSITORY/country-risk-model/"
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
```

Expected: Vite creates the skeleton; `npm install` finishes without errors.

- [ ] **Step 2: Verify it boots**

```bash
npm run dev
```

Visit `http://localhost:5173`. Expected: default Vite+React starter page. Stop with Ctrl-C.

- [ ] **Step 3: Add project dependencies**

```bash
cd frontend
npm i react-router-dom @tanstack/react-query @supabase/supabase-js zod clsx
npm i -D tailwindcss postcss autoprefixer vitest @testing-library/react @testing-library/jest-dom @testing-library/user-event jsdom @types/node
npx tailwindcss init -p
```

- [ ] **Step 4: Configure Tailwind — `frontend/tailwind.config.ts`**

Replace the auto-generated `tailwind.config.js` with `tailwind.config.ts`:

```ts
import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {},
  },
  plugins: [],
} satisfies Config;
```

Delete the auto-generated `tailwind.config.js` if it exists.

- [ ] **Step 5: Replace `frontend/src/index.css` with Tailwind directives**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

html, body, #root {
  height: 100%;
}
```

- [ ] **Step 6: Configure Vitest — append to `frontend/vite.config.ts`**

```ts
/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    globals: true,
    include: ["tests/**/*.test.tsx", "src/**/*.test.tsx"],
  },
});
```

- [ ] **Step 7: Create `frontend/tests/setup.ts`**

```ts
import "@testing-library/jest-dom";
```

- [ ] **Step 8: Add test script in `frontend/package.json`**

In `"scripts"` add (keep existing entries):

```json
    "test": "vitest run",
    "test:watch": "vitest"
```

- [ ] **Step 9: Commit**

```bash
git add frontend/
git commit -m "chore(frontend): Vite + React + TS + Tailwind + Vitest scaffold"
```

---

## Task 17: Frontend — env + Supabase client + API fetcher

**Files:**
- Create: `frontend/.env.example`
- Create: `frontend/src/lib/supabase.ts`
- Create: `frontend/src/lib/api.ts`
- Create: `frontend/src/vite-env.d.ts` (or modify existing)

- [ ] **Step 1: Create `frontend/.env.example`**

```
VITE_SUPABASE_URL=https://YOUR-DEV-PROJECT.supabase.co
VITE_SUPABASE_ANON_KEY=eyJhbGciOi...
VITE_API_BASE_URL=http://localhost:8000
```

Then create a real `frontend/.env` with your cloud dev project's URL and anon key (mirror the values you put in the repo-root `.env` in Task 2 — just the two prefixed with `VITE_`). `VITE_API_BASE_URL` stays pointed at your local FastAPI instance.

- [ ] **Step 2: Update `frontend/src/vite-env.d.ts`**

```ts
/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_SUPABASE_URL: string;
  readonly VITE_SUPABASE_ANON_KEY: string;
  readonly VITE_API_BASE_URL: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
```

- [ ] **Step 3: Create `frontend/src/lib/supabase.ts`**

```ts
import { createClient } from "@supabase/supabase-js";

export const supabase = createClient(
  import.meta.env.VITE_SUPABASE_URL,
  import.meta.env.VITE_SUPABASE_ANON_KEY,
);
```

- [ ] **Step 4: Create `frontend/src/lib/api.ts`**

```ts
import { z } from "zod";
import { supabase } from "./supabase";

const API_BASE = import.meta.env.VITE_API_BASE_URL;

export class ApiError extends Error {
  constructor(public status: number, message: string, public details?: unknown) {
    super(message);
  }
}

async function authHeader(): Promise<Record<string, string>> {
  const { data } = await supabase.auth.getSession();
  return data.session ? { Authorization: `Bearer ${data.session.access_token}` } : {};
}

async function request<T>(path: string, schema: z.ZodType<T>, init?: RequestInit): Promise<T> {
  const headers = { "Content-Type": "application/json", ...(await authHeader()), ...(init?.headers ?? {}) };
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!res.ok) {
    let body: unknown = null;
    try { body = await res.json(); } catch { /* ignore */ }
    throw new ApiError(res.status, res.statusText, body);
  }
  const json = await res.json();
  return schema.parse(json);
}

export const Country = z.object({
  iso3: z.string().length(3),
  name: z.string(),
  region: z.string().nullable().optional(),
});
export type Country = z.infer<typeof Country>;

export const Variable = z.object({
  code: z.string(),
  name: z.string(),
  category: z.string(),
  direction: z.string(),
  is_quantitative: z.boolean(),
  description: z.string().nullable().optional(),
});
export type Variable = z.infer<typeof Variable>;

export const api = {
  listCountries: () => request("/v1/countries", z.array(Country)),
  listVariables: () => request("/v1/variables", z.array(Variable)),
};
```

- [ ] **Step 5: Commit**

```bash
git add frontend/.env.example frontend/src/vite-env.d.ts frontend/src/lib/
git commit -m "feat(frontend): env + supabase client + typed API fetcher"
```

---

## Task 18: Frontend — Auth provider, login page, RequireAuth guard

**Files:**
- Create: `frontend/src/features/auth/AuthProvider.tsx`
- Create: `frontend/src/features/auth/LoginPage.tsx`
- Create: `frontend/src/features/auth/RequireAuth.tsx`
- Create: `frontend/tests/LoginPage.test.tsx`

- [ ] **Step 1: Create `frontend/src/features/auth/AuthProvider.tsx`**

```tsx
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import type { Session, User } from "@supabase/supabase-js";
import { supabase } from "../../lib/supabase";

type AuthState = { session: Session | null; user: User | null; loading: boolean };

const AuthContext = createContext<AuthState>({ session: null, user: null, loading: true });

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ session: null, user: null, loading: true });

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setState({ session: data.session, user: data.session?.user ?? null, loading: false });
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_event, session) => {
      setState({ session, user: session?.user ?? null, loading: false });
    });
    return () => sub.subscription.unsubscribe();
  }, []);

  return <AuthContext.Provider value={state}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}
```

- [ ] **Step 2: Create `frontend/src/features/auth/LoginPage.tsx`**

```tsx
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { supabase } from "../../lib/supabase";

export function LoginPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    setSubmitting(false);
    if (error) setError(error.message);
    else navigate("/", { replace: true });
  }

  return (
    <main className="flex min-h-full items-center justify-center bg-slate-50 p-6">
      <form onSubmit={onSubmit} className="w-full max-w-sm space-y-4 rounded-lg bg-white p-6 shadow">
        <h1 className="text-xl font-semibold text-slate-900">Sign in</h1>
        <label className="block text-sm">
          <span className="text-slate-700">Email</span>
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="mt-1 block w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
          />
        </label>
        <label className="block text-sm">
          <span className="text-slate-700">Password</span>
          <input
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1 block w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
          />
        </label>
        {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded bg-slate-900 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {submitting ? "Signing in..." : "Sign in"}
        </button>
      </form>
    </main>
  );
}
```

- [ ] **Step 3: Create `frontend/src/features/auth/RequireAuth.tsx`**

```tsx
import { type ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "./AuthProvider";

export function RequireAuth({ children }: { children: ReactNode }) {
  const { session, loading } = useAuth();
  if (loading) return <div className="p-6 text-sm text-slate-500">Loading...</div>;
  if (!session) return <Navigate to="/login" replace />;
  return <>{children}</>;
}
```

- [ ] **Step 4: Write test `frontend/tests/LoginPage.test.tsx`**

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { LoginPage } from "../src/features/auth/LoginPage";

vi.mock("../src/lib/supabase", () => ({
  supabase: {
    auth: {
      signInWithPassword: vi.fn().mockResolvedValue({ error: null }),
    },
  },
}));

describe("LoginPage", () => {
  it("renders email and password inputs and a submit button", () => {
    render(<MemoryRouter><LoginPage /></MemoryRouter>);
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument();
  });

  it("shows an error message when sign-in fails", async () => {
    const { supabase } = await import("../src/lib/supabase");
    (supabase.auth.signInWithPassword as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      error: { message: "Invalid login credentials" },
    });
    render(<MemoryRouter><LoginPage /></MemoryRouter>);
    await userEvent.type(screen.getByLabelText(/email/i), "u@example.com");
    await userEvent.type(screen.getByLabelText(/password/i), "wrong");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/invalid login credentials/i);
  });
});
```

- [ ] **Step 5: Run tests**

```bash
cd frontend && npm test
```

Expected: `2 passed`

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/auth/ frontend/tests/LoginPage.test.tsx
git commit -m "feat(frontend): auth provider, login page, RequireAuth guard"
```

---

## Task 19: Frontend — routes + country list page + app shell

**Files:**
- Create: `frontend/src/routes.tsx`
- Create: `frontend/src/components/AppShell.tsx`
- Create: `frontend/src/features/countries/CountryListPage.tsx`
- Create: `frontend/tests/CountryListPage.test.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/main.tsx`

- [ ] **Step 1: Create `frontend/src/components/AppShell.tsx`**

```tsx
import { type ReactNode } from "react";
import { Link } from "react-router-dom";
import { supabase } from "../lib/supabase";
import { useAuth } from "../features/auth/AuthProvider";

export function AppShell({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  return (
    <div className="flex min-h-full flex-col">
      <header className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3">
        <Link to="/" className="text-sm font-semibold text-slate-900">Country Risk Model</Link>
        <div className="flex items-center gap-3 text-sm">
          <nav className="flex gap-3">
            <Link to="/countries" className="text-slate-700 hover:underline">Countries</Link>
          </nav>
          {user && (
            <button
              onClick={() => supabase.auth.signOut()}
              className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-700 hover:bg-slate-50"
            >
              Sign out
            </button>
          )}
        </div>
      </header>
      <main className="flex-1 bg-slate-50 p-6">{children}</main>
    </div>
  );
}
```

- [ ] **Step 2: Create `frontend/src/features/countries/CountryListPage.tsx`**

```tsx
import { useQuery } from "@tanstack/react-query";
import { api, type Country } from "../../lib/api";

export function CountryListPage() {
  const { data, isLoading, error } = useQuery({ queryKey: ["countries"], queryFn: api.listCountries });

  if (isLoading) return <p className="text-sm text-slate-500">Loading countries...</p>;
  if (error) return <p role="alert" className="text-sm text-red-600">{(error as Error).message}</p>;

  const countries = data ?? [];
  return (
    <section>
      <h1 className="mb-4 text-lg font-semibold text-slate-900">Countries ({countries.length})</h1>
      <ul className="divide-y divide-slate-200 rounded border border-slate-200 bg-white">
        {countries.map((c: Country) => (
          <li key={c.iso3} className="flex items-center justify-between px-4 py-2 text-sm">
            <span className="text-slate-900">{c.name}</span>
            <span className="text-xs text-slate-500">{c.iso3}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
```

- [ ] **Step 3: Create `frontend/src/routes.tsx`**

```tsx
import { createBrowserRouter, Navigate } from "react-router-dom";
import { LoginPage } from "./features/auth/LoginPage";
import { RequireAuth } from "./features/auth/RequireAuth";
import { AppShell } from "./components/AppShell";
import { CountryListPage } from "./features/countries/CountryListPage";

function LandingRedirect() {
  // v1: everyone lands on /countries. Role-aware routing refines in later plans.
  return <Navigate to="/countries" replace />;
}

export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  {
    path: "/",
    element: (
      <RequireAuth>
        <AppShell>
          <LandingRedirect />
        </AppShell>
      </RequireAuth>
    ),
  },
  {
    path: "/countries",
    element: (
      <RequireAuth>
        <AppShell>
          <CountryListPage />
        </AppShell>
      </RequireAuth>
    ),
  },
]);
```

- [ ] **Step 4: Replace `frontend/src/App.tsx`**

```tsx
import { RouterProvider } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "./features/auth/AuthProvider";
import { router } from "./routes";

const qc = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </QueryClientProvider>
  );
}
```

- [ ] **Step 5: Ensure `frontend/src/main.tsx` imports `./index.css`**

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
```

- [ ] **Step 6: Write test `frontend/tests/CountryListPage.test.tsx`**

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CountryListPage } from "../src/features/countries/CountryListPage";

vi.mock("../src/lib/api", () => ({
  api: {
    listCountries: vi.fn().mockResolvedValue([
      { iso3: "USA", name: "UNITED STATES", region: "DEVELOPED" },
      { iso3: "ZAF", name: "SOUTH AFRICA", region: "AFRICA" },
    ]),
  },
}));

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>;
}

describe("CountryListPage", () => {
  it("renders the count and each country row", async () => {
    render(wrap(<CountryListPage />));
    await waitFor(() => expect(screen.getByText(/countries \(2\)/i)).toBeInTheDocument());
    expect(screen.getByText(/united states/i)).toBeInTheDocument();
    expect(screen.getByText(/south africa/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 7: Run frontend tests**

```bash
cd frontend && npm test
```

Expected: `3 passed`

- [ ] **Step 8: Manual smoke**

In two terminals:

```bash
cd backend && .venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev
```

Visit `http://localhost:5173`. You should be redirected to `/login`. Sign in with the owner user from Task 8. You should land on `/countries` and see 161 rows.

- [ ] **Step 9: Commit**

```bash
git add frontend/src frontend/tests/CountryListPage.test.tsx
git commit -m "feat(frontend): router + AppShell + country list page"
```

---

## Task 20: GitHub Actions CI

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Create `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]

jobs:
  backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install backend deps
        working-directory: backend
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev]"
      - name: Ruff
        working-directory: backend
        run: ruff check app tests
      - name: Pytest (unit only)
        working-directory: backend
        env:
          SUPABASE_URL: https://example.supabase.co
          SUPABASE_ANON_KEY: anon
          SUPABASE_SERVICE_ROLE_KEY: service
          SUPABASE_JWT_SECRET: test-jwt-secret
        run: pytest -v

  frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: "npm"
          cache-dependency-path: frontend/package-lock.json
      - name: Install frontend deps
        working-directory: frontend
        run: npm ci
      - name: Typecheck
        working-directory: frontend
        run: npx tsc --noEmit
      - name: Test
        working-directory: frontend
        run: npm test
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: lint + typecheck + tests on PR and main"
```

---

## Task 21: Final integration smoke + Plan 1 tag

- [ ] **Step 1: Verify full stack against the dev cloud project**

The dev project should already have migrations + seed applied from earlier tasks. If anything looks off, re-run:

```bash
supabase db reset --linked   # destructive — wipes dev project, reapplies migrations + seed
# After reset, re-check that the two test users still exist in Studio → Authentication.
# Auth users survive `db reset`, but memberships do not (they were wiped), so re-run the Task 8 Step 4 SQL to recreate them.
```

Then run the test suites:

```bash
cd backend && .venv/Scripts/python -m pytest -v
cd ../frontend && npm test
```

Expected: all tests pass.

- [ ] **Step 2: Manual end-to-end**

Boot backend + frontend as in Task 19 Step 8. Log in as owner → see the full country list (~160). Log out. Log in as client_admin → same (both roles can read countries in this plan; role-specific UI comes in later plans). Log out.

- [ ] **Step 3: Tag**

```bash
git tag -a plan-1-foundation -m "Plan 1 complete: scaffold + auth + reference data"
```

- [ ] **Step 4: Final commit confirming README up to date (if any gaps)**

Skim `README.md` against what's now in the repo; update any stale steps. If no changes needed, skip.

---

## Validation Checklist (end-of-plan)

Tick these before declaring Plan 1 done:

- [ ] `supabase db reset --linked` succeeds end-to-end.
- [ ] `cd backend && pytest` passes with 0 failures (unit suite — integration run on demand).
- [ ] `cd frontend && npm test` passes with 0 failures.
- [ ] `cd frontend && npm run dev` serves the app; sign-in with the owner account completes and `/countries` shows ~160 rows.
- [ ] `GET http://localhost:8000/v1/health` returns `{"status":"ok","version":"0.1.0"}`.
- [ ] `GET http://localhost:8000/v1/countries` (with a valid owner JWT) returns the full country list (~160 rows, matching your CSV).
- [ ] GitHub Actions CI passes on the first PR.

When all ticked: ready for **Plan 2 — Scoring engine**, which will add `domain/` pure-Python logic and regression-test Python scores against the Excel prototype.
