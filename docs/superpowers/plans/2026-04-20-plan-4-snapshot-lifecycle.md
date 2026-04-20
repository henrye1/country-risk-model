# Plan 4 — Snapshot Lifecycle & Publish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the audit-gated scoring workflow that turns raw observations + trained models into versioned, published country scores. After this plan, an analyst can create a draft snapshot, compute scores for all countries at a given `as_of_date`, review a diff against the previous publish, and an owner can flip it to `published` — at which point the rows become immutable (DB-enforced) and stable identifiers become consumable by downstream PD/LGD systems.

**Architecture:** Three new tables (`score_snapshots`, `country_scores`, `driver_scores`) with PostgreSQL triggers enforcing immutability of published rows and valid status transitions (`draft → published → archived`). A lightweight `audit_log` table records sensitive actions. A new `app/services/snapshot.py` orchestrates: fetch latest raw observations as of date → load trained model → apply `domain/scoring.py::score_country` per country → persist draft rows. New admin endpoints expose create/compute/diff/publish/archive. All domain logic stays pure Python; FastAPI and Supabase remain at the edges.

**Tech Stack:** Python 3.12 (FastAPI, httpx, pytest), Supabase Postgres (new tables + triggers), existing domain/scoring.py and trained model versions from Plan 2.

**Precondition:** Plan 3 tagged `plan-3-ingestion`. Repo at `C:/Users/APR/OneDrive - Anchor Point Risk (Pty) Ltd/Desktop/VS_CODE_REPOSITORY/country-risk-model/`. `raw_observations` table has multi-year data populated (verified: 24k rows across 5 variables, 1960–2024). Trained model versions from Plan 2 still exist in `model_versions` (HIGH + LOW).

---

## Design notes (read before starting)

### Missing data handling
A trained model requires all its quant + qual variables. For Plan 4 we **skip any country that is missing at least one driver as of the snapshot date**. Skipped countries are counted and returned in the compute response; they do not produce a `country_scores` row. Later plans can add default-fill if needed.

### Segment selection
Each country's segment is looked up from `country_segments` using the most recent `as_of_year <= year_of(snapshot.as_of_date)`. A country with no segment row is skipped.

### "Latest raw observation as of date" semantics
For each `(iso3, variable_code)`, the service pulls the raw observation with the **largest `year` ≤ snapshot year**, breaking ties by **largest `ingested_at`** (latest-wins for corrections). We do this in Python after a single bulk fetch — avoiding Postgres `DISTINCT ON` which Supabase-py doesn't expose cleanly.

### Idempotency
- `/compute` is idempotent for draft snapshots: wipes existing draft rows and rewrites them in one transaction-per-chunk operation.
- `/publish` accepts an `Idempotency-Key` header — repeated calls within 24h return the original response (stored in-memory for v1; Redis-backed key store is a future plan).

### What Plan 4 does NOT cover (deferred)
- Notifications fan-out on publish (Plan 6)
- Frontend snapshot-review UI (Plan 5)
- Aggregate/derived variables (5-year inflation averages etc.)
- Background worker (queue-based compute) — current compute is synchronous, fine for 161 countries

---

## File Structure After This Plan

```
country-risk-model/
├── backend/
│   ├── app/
│   │   ├── repositories/
│   │   │   ├── raw_observations.py          # MODIFY: add latest_observations_up_to_year()
│   │   │   └── snapshot.py                  # NEW
│   │   ├── services/
│   │   │   └── snapshot.py                  # NEW: compute + publish orchestration
│   │   ├── api/
│   │   │   └── admin.py                     # MODIFY: add snapshot routes
│   │   └── schemas/
│   │       └── snapshot.py                  # NEW
│   └── tests/
│       ├── services/                        # NEW folder
│       │   ├── __init__.py
│       │   └── test_snapshot_service.py
│       └── api/
│           └── test_admin_snapshots.py      # NEW
└── supabase/
    └── migrations/
        ├── 20260420000001_score_snapshots.sql    # tables + RLS
        ├── 20260420000002_score_triggers.sql     # immutability + transitions
        └── 20260420000003_audit_log.sql          # audit trail
```

---

## Task 1: Migration — score snapshot tables

**Files:**
- Create: `supabase/migrations/20260420000001_score_snapshots.sql`

- [ ] **Step 1: Write the migration**

```sql
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
```

- [ ] **Step 2: Apply**

```bash
/c/Users/APR/scoop/shims/supabase.exe db push --linked
```

Expected: `Applying migration 20260420000001_score_snapshots.sql... Finished supabase db push.`

- [ ] **Step 3: Idempotency verify**

```bash
/c/Users/APR/scoop/shims/supabase.exe db push --linked
```

Expected: `Remote database is up to date.`

- [ ] **Step 4: Commit + push**

```bash
cd "C:/Users/APR/OneDrive - Anchor Point Risk (Pty) Ltd/Desktop/VS_CODE_REPOSITORY/country-risk-model/"
git add supabase/migrations/20260420000001_score_snapshots.sql
git commit -m "feat(db): score_snapshots + country_scores + driver_scores tables with RLS"
git push
```

---

## Task 2: Migration — immutability triggers + status transition guards

**Files:**
- Create: `supabase/migrations/20260420000002_score_triggers.sql`

- [ ] **Step 1: Write the migration**

```sql
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
```

- [ ] **Step 2: Apply**

```bash
/c/Users/APR/scoop/shims/supabase.exe db push --linked
```

Expected: `Applying migration 20260420000002_score_triggers.sql... Finished supabase db push.`

- [ ] **Step 3: Idempotency verify**

```bash
/c/Users/APR/scoop/shims/supabase.exe db push --linked
```

- [ ] **Step 4: Commit + push**

```bash
git add supabase/migrations/20260420000002_score_triggers.sql
git commit -m "feat(db): immutability + status-transition triggers on score snapshots"
git push
```

---

## Task 3: Migration — audit log table

**Files:**
- Create: `supabase/migrations/20260420000003_audit_log.sql`

- [ ] **Step 1: Write the migration**

```sql
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
```

- [ ] **Step 2: Apply**

```bash
/c/Users/APR/scoop/shims/supabase.exe db push --linked
```

- [ ] **Step 3: Commit + push**

```bash
git add supabase/migrations/20260420000003_audit_log.sql
git commit -m "feat(db): audit_log table for sensitive-action tracking"
git push
```

---

## Task 4: Extend raw_observations repository with "latest-as-of" helper

**Files:**
- Modify: `backend/app/repositories/raw_observations.py` — add method

- [ ] **Step 1: Add the method**

Use the Edit tool. After the existing `known_iso3_codes` method (before the end of the class), add:

```python
    def fetch_observations_up_to_year(self, max_year: int) -> list[dict]:
        """Return every raw observation whose year <= max_year and value is not null.

        Returned dicts contain iso3, variable_code, year, value, ingested_at.
        Callers reduce to "latest per (iso3, variable_code)" in Python.
        """
        # Supabase-py: paginate to get all rows (range fetch).
        all_rows: list[dict] = []
        page_size = 1000
        start = 0
        while True:
            resp = (
                self._client.table("raw_observations")
                .select("iso3, variable_code, year, value, ingested_at")
                .lte("year", max_year)
                .not_.is_("value", "null")
                .order("ingested_at", desc=True)
                .range(start, start + page_size - 1)
                .execute()
            )
            batch = resp.data
            if not batch:
                break
            all_rows.extend(batch)
            if len(batch) < page_size:
                break
            start += page_size
        return all_rows
```

- [ ] **Step 2: Smoke-test**

```bash
cd backend
./.venv/Scripts/python.exe -c "from app.repositories.raw_observations import RawObservationRepository; print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Commit + push**

```bash
cd ..
git add backend/app/repositories/raw_observations.py
git commit -m "feat(backend): raw_observations — fetch all obs up to a year (for scoring)"
git push
```

---

## Task 5: Snapshot repository

**Files:**
- Create: `backend/app/repositories/snapshot.py`

- [ ] **Step 1: Create the file**

```python
"""Persist + read score_snapshots, country_scores, driver_scores.

Writes use service_client (service_role); reads route through whichever client
the caller provides (typically user_client for RLS enforcement on /v1/ reads,
service_client for internal admin reads)."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from supabase import Client


@dataclass
class DraftSnapshotCreate:
    name: str
    as_of_date: date
    model_version_high: UUID | None
    model_version_low: UUID | None
    model_version_nodata: UUID | None
    created_by: UUID | None


@dataclass
class CountryScoreRow:
    iso3: str
    segment: str
    final_score: float
    quant_score: float
    qual_score: float
    bucket_band: str | None


@dataclass
class DriverScoreRow:
    iso3: str
    variable_code: str
    raw_value: float | None
    standardised_value: float | None
    bucket_score: float | None
    contribution: float


class SnapshotRepository:
    def __init__(self, client: Client) -> None:
        self._client = client

    # --- CRUD on score_snapshots ---

    def create_draft(self, draft: DraftSnapshotCreate) -> UUID:
        payload: dict[str, Any] = {
            "name": draft.name,
            "as_of_date": draft.as_of_date.isoformat(),
            "status": "draft",
            "model_version_high": str(draft.model_version_high) if draft.model_version_high else None,
            "model_version_low": str(draft.model_version_low) if draft.model_version_low else None,
            "model_version_nodata": str(draft.model_version_nodata) if draft.model_version_nodata else None,
            "created_by": str(draft.created_by) if draft.created_by else None,
        }
        resp = self._client.table("score_snapshots").insert(payload).execute()
        return UUID(resp.data[0]["id"])

    def get(self, snapshot_id: UUID) -> dict:
        resp = (
            self._client.table("score_snapshots")
            .select("*")
            .eq("id", str(snapshot_id))
            .single()
            .execute()
        )
        return resp.data

    def list_snapshots(self, statuses: list[str] | None = None, limit: int = 50) -> list[dict]:
        q = self._client.table("score_snapshots").select("*").order("as_of_date", desc=True).limit(limit)
        if statuses:
            q = q.in_("status", statuses)
        return q.execute().data

    def publish(self, snapshot_id: UUID, published_by: UUID | None, notes: str | None) -> dict:
        payload: dict[str, Any] = {
            "status": "published",
            "published_at": datetime.utcnow().isoformat() + "Z",
            "published_notes": notes,
        }
        if published_by is not None:
            payload["published_by"] = str(published_by)
        resp = (
            self._client.table("score_snapshots")
            .update(payload)
            .eq("id", str(snapshot_id))
            .execute()
        )
        return resp.data[0]

    def archive(self, snapshot_id: UUID) -> dict:
        resp = (
            self._client.table("score_snapshots")
            .update({"status": "archived"})
            .eq("id", str(snapshot_id))
            .execute()
        )
        return resp.data[0]

    # --- Writing draft score rows ---

    def wipe_draft_scores(self, snapshot_id: UUID) -> None:
        """Delete all country_scores + driver_scores for a snapshot.
        The DB trigger blocks this if the snapshot is published."""
        self._client.table("driver_scores").delete().eq("snapshot_id", str(snapshot_id)).execute()
        self._client.table("country_scores").delete().eq("snapshot_id", str(snapshot_id)).execute()

    def insert_country_scores(
        self, snapshot_id: UUID, rows: list[CountryScoreRow]
    ) -> int:
        if not rows:
            return 0
        payload = [
            {
                "snapshot_id": str(snapshot_id),
                "iso3": r.iso3,
                "segment": r.segment,
                "final_score": r.final_score,
                "quant_score": r.quant_score,
                "qual_score": r.qual_score,
                "bucket_band": r.bucket_band,
            }
            for r in rows
        ]
        return _chunked_insert(self._client, "country_scores", payload)

    def insert_driver_scores(
        self, snapshot_id: UUID, rows: list[DriverScoreRow]
    ) -> int:
        if not rows:
            return 0
        payload = [
            {
                "snapshot_id": str(snapshot_id),
                "iso3": r.iso3,
                "variable_code": r.variable_code,
                "raw_value": r.raw_value,
                "standardised_value": r.standardised_value,
                "bucket_score": r.bucket_score,
                "contribution": r.contribution,
            }
            for r in rows
        ]
        return _chunked_insert(self._client, "driver_scores", payload)

    # --- Reads for diff computation ---

    def latest_published_snapshot(self) -> dict | None:
        resp = (
            self._client.table("score_snapshots")
            .select("*")
            .eq("status", "published")
            .order("published_at", desc=True)
            .limit(1)
            .execute()
        )
        return resp.data[0] if resp.data else None

    def country_scores_for(self, snapshot_id: UUID) -> list[dict]:
        resp = (
            self._client.table("country_scores")
            .select("iso3, segment, final_score, quant_score, qual_score, bucket_band")
            .eq("snapshot_id", str(snapshot_id))
            .execute()
        )
        return resp.data


def _chunked_insert(client: Client, table: str, rows: list[dict], chunk_size: int = 500) -> int:
    """Insert in chunks to stay under Supabase-py batch limits."""
    inserted = 0
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i : i + chunk_size]
        resp = client.table(table).insert(chunk).execute()
        inserted += len(resp.data)
    return inserted
```

- [ ] **Step 2: Smoke-import**

```bash
cd backend
./.venv/Scripts/python.exe -c "from app.repositories.snapshot import SnapshotRepository, DraftSnapshotCreate, CountryScoreRow, DriverScoreRow; print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Commit + push**

```bash
cd ..
git add backend/app/repositories/snapshot.py
git commit -m "feat(backend): snapshot repository (CRUD + score-row batch insert)"
git push
```

---

## Task 6: Snapshot service (TDD with stubs)

**Files:**
- Create: `backend/tests/services/__init__.py`
- Create: `backend/tests/services/test_snapshot_service.py`
- Create: `backend/app/services/snapshot.py`

- [ ] **Step 1: Create tests/services package marker**

```bash
cd "C:/Users/APR/OneDrive - Anchor Point Risk (Pty) Ltd/Desktop/VS_CODE_REPOSITORY/country-risk-model/"
mkdir -p backend/tests/services
touch backend/tests/services/__init__.py
```

- [ ] **Step 2: Write failing test `backend/tests/services/test_snapshot_service.py`**

```python
from __future__ import annotations
from datetime import date
from uuid import UUID, uuid4

import pytest

from app.domain.types import (
    Bucket,
    ModelCoefficient,
    StandardisationParam,
    TrainedModel,
)
from app.repositories.snapshot import (
    CountryScoreRow,
    DraftSnapshotCreate,
    DriverScoreRow,
)
from app.services.snapshot import (
    ComputeResult,
    MissingModelVersion,
    SnapshotService,
)


# --- Stubs ---------------------------------------------------------------

def _toy_model(segment: str = "HIGH") -> TrainedModel:
    return TrainedModel(
        segment=segment,  # type: ignore[arg-type]
        coefficients=(
            ModelCoefficient(variable_code=None, coefficient=0.0, is_intercept=True),
            ModelCoefficient(variable_code="pr", coefficient=1.0, is_intercept=False),
        ),
        standardisation=(
            StandardisationParam(variable_code="gdp_capita", mean=10000.0, std=5000.0),
        ),
        buckets=(
            Bucket(variable_code="gdp_capita", bucket_order=0, lower_bound=None, upper_bound=0.0, score=-1.0),
            Bucket(variable_code="gdp_capita", bucket_order=1, lower_bound=0.0, upper_bound=None, score=1.0),
        ),
        quant_variable_codes=("gdp_capita",),
        qual_variable_codes=("pr",),
        training_data_hash="abc" * 20,
        fit_metrics={"r2": 0.5},
    )


class FakeObservationsRepo:
    def __init__(self, observations: list[dict], known_iso3: set[str]) -> None:
        self._obs = observations
        self._iso3 = known_iso3

    def fetch_observations_up_to_year(self, max_year: int) -> list[dict]:
        return [o for o in self._obs if o["year"] <= max_year and o["value"] is not None]

    def known_iso3_codes(self) -> set[str]:
        return set(self._iso3)


class FakeModelRepo:
    def __init__(self, models: dict[UUID, TrainedModel]) -> None:
        self._models = models

    def load(self, model_version_id: UUID) -> TrainedModel:
        return self._models[model_version_id]


class FakeSnapshotRepo:
    def __init__(self) -> None:
        self.snapshot_id = uuid4()
        self.country_score_rows: list[CountryScoreRow] = []
        self.driver_score_rows: list[DriverScoreRow] = []
        self.created_draft: DraftSnapshotCreate | None = None
        self.wipes = 0

    def create_draft(self, draft: DraftSnapshotCreate) -> UUID:
        self.created_draft = draft
        return self.snapshot_id

    def wipe_draft_scores(self, snapshot_id: UUID) -> None:
        self.wipes += 1

    def insert_country_scores(self, snapshot_id: UUID, rows: list[CountryScoreRow]) -> int:
        assert snapshot_id == self.snapshot_id
        self.country_score_rows.extend(rows)
        return len(rows)

    def insert_driver_scores(self, snapshot_id: UUID, rows: list[DriverScoreRow]) -> int:
        assert snapshot_id == self.snapshot_id
        self.driver_score_rows.extend(rows)
        return len(rows)


class FakeSegmentRepo:
    """Returns {iso3: segment_code} for the most recent year <= year_of(as_of_date)."""

    def __init__(self, segments: dict[str, str]) -> None:
        self._segments = segments

    def segment_by_iso3_as_of(self, as_of_year: int) -> dict[str, str]:
        return dict(self._segments)


# --- Tests ---------------------------------------------------------------

def test_compute_produces_one_country_and_n_driver_rows_per_scorable_country():
    model_id_high = uuid4()
    obs_repo = FakeObservationsRepo(
        observations=[
            {"iso3": "USA", "variable_code": "gdp_capita", "year": 2022, "value": 70000.0, "ingested_at": "2026-04-01T00:00:00Z"},
            {"iso3": "USA", "variable_code": "pr", "year": 2022, "value": 1.0, "ingested_at": "2026-04-01T00:00:00Z"},
            {"iso3": "ZAF", "variable_code": "gdp_capita", "year": 2022, "value": 6000.0, "ingested_at": "2026-04-01T00:00:00Z"},
            {"iso3": "ZAF", "variable_code": "pr", "year": 2022, "value": 0.2, "ingested_at": "2026-04-01T00:00:00Z"},
        ],
        known_iso3={"USA", "ZAF"},
    )
    model_repo = FakeModelRepo({model_id_high: _toy_model("HIGH")})
    snapshot_repo = FakeSnapshotRepo()
    segment_repo = FakeSegmentRepo({"USA": "HIGH", "ZAF": "HIGH"})

    service = SnapshotService(
        obs_repo=obs_repo,
        model_repo=model_repo,
        snapshot_repo=snapshot_repo,
        segment_repo=segment_repo,
    )

    snapshot_id = service.create_draft(
        name="2026-Q2",
        as_of_date=date(2022, 12, 31),
        model_version_high=model_id_high,
        model_version_low=None,
        model_version_nodata=None,
        created_by=None,
    )
    result = service.compute(snapshot_id)

    assert isinstance(result, ComputeResult)
    assert result.countries_scored == 2
    assert result.countries_skipped_missing_data == 0
    assert result.countries_skipped_no_model == 0
    assert len(snapshot_repo.country_score_rows) == 2
    assert len(snapshot_repo.driver_score_rows) == 4  # 2 countries × 2 drivers
    assert snapshot_repo.wipes == 1


def test_compute_skips_country_with_missing_driver():
    model_id_high = uuid4()
    obs_repo = FakeObservationsRepo(
        observations=[
            {"iso3": "USA", "variable_code": "gdp_capita", "year": 2022, "value": 70000.0, "ingested_at": "2026-04-01T00:00:00Z"},
            # USA missing pr — should be skipped.
            {"iso3": "ZAF", "variable_code": "gdp_capita", "year": 2022, "value": 6000.0, "ingested_at": "2026-04-01T00:00:00Z"},
            {"iso3": "ZAF", "variable_code": "pr", "year": 2022, "value": 0.2, "ingested_at": "2026-04-01T00:00:00Z"},
        ],
        known_iso3={"USA", "ZAF"},
    )
    model_repo = FakeModelRepo({model_id_high: _toy_model("HIGH")})
    snapshot_repo = FakeSnapshotRepo()
    segment_repo = FakeSegmentRepo({"USA": "HIGH", "ZAF": "HIGH"})

    service = SnapshotService(
        obs_repo=obs_repo,
        model_repo=model_repo,
        snapshot_repo=snapshot_repo,
        segment_repo=segment_repo,
    )
    snapshot_id = service.create_draft(
        name="test",
        as_of_date=date(2022, 12, 31),
        model_version_high=model_id_high,
        model_version_low=None,
        model_version_nodata=None,
        created_by=None,
    )
    result = service.compute(snapshot_id)

    assert result.countries_scored == 1
    assert result.countries_skipped_missing_data == 1
    iso3s = {r.iso3 for r in snapshot_repo.country_score_rows}
    assert iso3s == {"ZAF"}


def test_compute_skips_country_with_no_model_for_its_segment():
    obs_repo = FakeObservationsRepo(observations=[], known_iso3={"USA"})
    model_repo = FakeModelRepo({})
    snapshot_repo = FakeSnapshotRepo()
    segment_repo = FakeSegmentRepo({"USA": "HIGH"})

    service = SnapshotService(
        obs_repo=obs_repo,
        model_repo=model_repo,
        snapshot_repo=snapshot_repo,
        segment_repo=segment_repo,
    )

    snapshot_id = service.create_draft(
        name="test",
        as_of_date=date(2022, 12, 31),
        model_version_high=None,   # no HIGH model
        model_version_low=None,
        model_version_nodata=None,
        created_by=None,
    )
    result = service.compute(snapshot_id)

    assert result.countries_scored == 0
    assert result.countries_skipped_no_model == 1


def test_compute_uses_latest_ingested_when_multiple_rows_for_same_year():
    model_id_high = uuid4()
    obs_repo = FakeObservationsRepo(
        observations=[
            # Two rows for USA gdp_capita in 2022 — latest ingested should win.
            {"iso3": "USA", "variable_code": "gdp_capita", "year": 2022, "value": 50000.0, "ingested_at": "2026-01-01T00:00:00Z"},
            {"iso3": "USA", "variable_code": "gdp_capita", "year": 2022, "value": 70000.0, "ingested_at": "2026-04-01T00:00:00Z"},
            {"iso3": "USA", "variable_code": "pr", "year": 2022, "value": 1.0, "ingested_at": "2026-04-01T00:00:00Z"},
        ],
        known_iso3={"USA"},
    )
    model_repo = FakeModelRepo({model_id_high: _toy_model("HIGH")})
    snapshot_repo = FakeSnapshotRepo()
    segment_repo = FakeSegmentRepo({"USA": "HIGH"})

    service = SnapshotService(
        obs_repo=obs_repo,
        model_repo=model_repo,
        snapshot_repo=snapshot_repo,
        segment_repo=segment_repo,
    )
    snapshot_id = service.create_draft(
        name="t", as_of_date=date(2022, 12, 31),
        model_version_high=model_id_high,
        model_version_low=None, model_version_nodata=None, created_by=None,
    )
    service.compute(snapshot_id)

    gdp_driver = next(r for r in snapshot_repo.driver_score_rows if r.variable_code == "gdp_capita")
    assert gdp_driver.raw_value == 70000.0
```

- [ ] **Step 3: Run — confirm failure**

```bash
cd backend
source .venv/Scripts/activate
pytest tests/services/test_snapshot_service.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.services.snapshot'`.

- [ ] **Step 4: Implement `backend/app/services/snapshot.py`**

```python
"""Snapshot orchestration: create draft → compute scores → (later) publish."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol
from uuid import UUID

from app.domain.scoring import score_country
from app.domain.types import DriverInput, TrainedModel
from app.repositories.snapshot import (
    CountryScoreRow,
    DraftSnapshotCreate,
    DriverScoreRow,
)


class MissingModelVersion(ValueError):
    """Raised when a required model version is not available for a segment."""


class ObservationsRepoProtocol(Protocol):
    def fetch_observations_up_to_year(self, max_year: int) -> list[dict]: ...
    def known_iso3_codes(self) -> set[str]: ...


class ModelRepoProtocol(Protocol):
    def load(self, model_version_id: UUID) -> TrainedModel: ...


class SnapshotRepoProtocol(Protocol):
    def create_draft(self, draft: DraftSnapshotCreate) -> UUID: ...
    def wipe_draft_scores(self, snapshot_id: UUID) -> None: ...
    def insert_country_scores(self, snapshot_id: UUID, rows: list[CountryScoreRow]) -> int: ...
    def insert_driver_scores(self, snapshot_id: UUID, rows: list[DriverScoreRow]) -> int: ...


class SegmentRepoProtocol(Protocol):
    def segment_by_iso3_as_of(self, as_of_year: int) -> dict[str, str]: ...


@dataclass
class ComputeResult:
    snapshot_id: UUID
    countries_scored: int
    countries_skipped_missing_data: int
    countries_skipped_no_model: int
    countries_skipped_no_segment: int
    warnings: list[str] = field(default_factory=list)


class SnapshotService:
    def __init__(
        self,
        obs_repo: ObservationsRepoProtocol,
        model_repo: ModelRepoProtocol,
        snapshot_repo: SnapshotRepoProtocol,
        segment_repo: SegmentRepoProtocol,
    ) -> None:
        self._obs = obs_repo
        self._models = model_repo
        self._snapshots = snapshot_repo
        self._segments = segment_repo
        # Cache created-draft config so compute() can see it without a round trip.
        self._drafts: dict[UUID, DraftSnapshotCreate] = {}

    def create_draft(
        self,
        name: str,
        as_of_date: date,
        model_version_high: UUID | None,
        model_version_low: UUID | None,
        model_version_nodata: UUID | None,
        created_by: UUID | None,
    ) -> UUID:
        draft = DraftSnapshotCreate(
            name=name,
            as_of_date=as_of_date,
            model_version_high=model_version_high,
            model_version_low=model_version_low,
            model_version_nodata=model_version_nodata,
            created_by=created_by,
        )
        snapshot_id = self._snapshots.create_draft(draft)
        self._drafts[snapshot_id] = draft
        return snapshot_id

    def compute(self, snapshot_id: UUID) -> ComputeResult:
        draft = self._drafts.get(snapshot_id)
        if draft is None:
            raise KeyError(f"no draft cached for snapshot {snapshot_id}")

        as_of_year = draft.as_of_date.year

        # Load models per segment (only those the user requested).
        loaded_models: dict[str, TrainedModel] = {}
        for segment, version_id in [
            ("HIGH", draft.model_version_high),
            ("LOW", draft.model_version_low),
            ("NODATA", draft.model_version_nodata),
        ]:
            if version_id is not None:
                loaded_models[segment] = self._models.load(version_id)

        # Build a (iso3, variable_code) -> raw value lookup from latest observation.
        observations = self._obs.fetch_observations_up_to_year(as_of_year)
        latest: dict[tuple[str, str], dict] = {}
        for obs in observations:
            key = (obs["iso3"], obs["variable_code"])
            cur = latest.get(key)
            if cur is None:
                latest[key] = obs
                continue
            # Keep the one with the greatest year; break ties by ingested_at desc.
            if obs["year"] > cur["year"] or (
                obs["year"] == cur["year"] and obs["ingested_at"] > cur["ingested_at"]
            ):
                latest[key] = obs

        raw_by_country: dict[str, dict[str, float]] = {}
        for (iso3, code), obs in latest.items():
            raw_by_country.setdefault(iso3, {})[code] = float(obs["value"])

        segments_by_iso3 = self._segments.segment_by_iso3_as_of(as_of_year)
        known_iso3 = self._obs.known_iso3_codes()

        # Clear any prior draft rows (idempotent recompute).
        self._snapshots.wipe_draft_scores(snapshot_id)

        country_rows: list[CountryScoreRow] = []
        driver_rows: list[DriverScoreRow] = []
        scored = skipped_missing = skipped_no_model = skipped_no_segment = 0

        for iso3 in sorted(known_iso3):
            segment = segments_by_iso3.get(iso3)
            if segment is None:
                skipped_no_segment += 1
                continue

            model = loaded_models.get(segment)
            if model is None:
                skipped_no_model += 1
                continue

            drivers = raw_by_country.get(iso3, {})
            required = set(model.quant_variable_codes) | set(model.qual_variable_codes)
            missing = required - drivers.keys()
            if missing:
                skipped_missing += 1
                continue

            inputs = tuple(
                DriverInput(variable_code=code, raw_value=drivers[code])
                for code in required
            )
            result = score_country(iso3=iso3, model=model, inputs=inputs)

            country_rows.append(CountryScoreRow(
                iso3=iso3,
                segment=segment,
                final_score=result.final_score,
                quant_score=result.quant_score,
                qual_score=result.qual_score,
                bucket_band=None,  # banding deferred; placeholder for later plan
            ))
            for ds in result.driver_scores:
                driver_rows.append(DriverScoreRow(
                    iso3=iso3,
                    variable_code=ds.variable_code,
                    raw_value=ds.raw_value,
                    standardised_value=ds.standardised_value,
                    bucket_score=ds.bucket_score,
                    contribution=ds.contribution,
                ))
            scored += 1

        self._snapshots.insert_country_scores(snapshot_id, country_rows)
        self._snapshots.insert_driver_scores(snapshot_id, driver_rows)

        return ComputeResult(
            snapshot_id=snapshot_id,
            countries_scored=scored,
            countries_skipped_missing_data=skipped_missing,
            countries_skipped_no_model=skipped_no_model,
            countries_skipped_no_segment=skipped_no_segment,
        )
```

- [ ] **Step 5: Run — should pass**

```bash
pytest tests/services/test_snapshot_service.py -v
```

Expected: `4 passed`.

- [ ] **Step 6: Full suite — no regressions**

```bash
pytest -v
```

Expected: 37 passed, 5 deselected (33 prior + 4 new).

- [ ] **Step 7: Commit + push**

```bash
cd ..
git add backend/app/services/snapshot.py backend/tests/services
git commit -m "feat(services): snapshot service — create draft + compute scores (TDD)"
git push
```

---

## Task 7: Segment repository

**Files:**
- Create: `backend/app/repositories/segment.py`

- [ ] **Step 1: Create the file**

```python
"""Segment assignment lookup from country_segments table."""
from __future__ import annotations
from supabase import Client


class SegmentRepository:
    def __init__(self, client: Client) -> None:
        self._client = client

    def segment_by_iso3_as_of(self, as_of_year: int) -> dict[str, str]:
        """For each country, return its segment as of the most recent as_of_year
        <= the given year. Countries with no matching row are omitted."""
        resp = (
            self._client.table("country_segments")
            .select("iso3, as_of_year, segment")
            .lte("as_of_year", as_of_year)
            .order("as_of_year", desc=True)
            .execute()
        )
        latest: dict[str, str] = {}
        for row in resp.data:
            # First occurrence of an iso3 in desc-year order = its latest valid segment.
            latest.setdefault(row["iso3"], row["segment"])
        return latest
```

- [ ] **Step 2: Smoke-import**

```bash
cd backend
./.venv/Scripts/python.exe -c "from app.repositories.segment import SegmentRepository; print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Commit + push**

```bash
cd ..
git add backend/app/repositories/segment.py
git commit -m "feat(backend): segment repository — latest segment per country as of year"
git push
```

---

## Task 8: Snapshot schemas + admin endpoints

**Files:**
- Create: `backend/app/schemas/snapshot.py`
- Modify: `backend/app/api/admin.py` — add snapshot routes
- Modify: `backend/app/services/snapshot.py` — add publish + archive + diff methods

- [ ] **Step 1: Create `backend/app/schemas/snapshot.py`**

```python
from __future__ import annotations
from datetime import date, datetime
from uuid import UUID
from pydantic import BaseModel, Field


class CreateSnapshotRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    as_of_date: date
    model_version_high: UUID | None = None
    model_version_low: UUID | None = None
    model_version_nodata: UUID | None = None


class ComputeSummaryOut(BaseModel):
    snapshot_id: UUID
    countries_scored: int
    countries_skipped_missing_data: int
    countries_skipped_no_model: int
    countries_skipped_no_segment: int
    warnings: list[str] = Field(default_factory=list)


class SnapshotOut(BaseModel):
    id: UUID
    name: str
    as_of_date: date
    status: str
    model_version_high: UUID | None
    model_version_low: UUID | None
    model_version_nodata: UUID | None
    created_by: UUID | None
    created_at: datetime
    published_by: UUID | None = None
    published_at: datetime | None = None
    published_notes: str | None = None


class PublishRequest(BaseModel):
    notes: str | None = None


class DiffRowOut(BaseModel):
    iso3: str
    segment: str
    new_score: float | None
    previous_score: float | None
    delta: float | None


class DiffOut(BaseModel):
    snapshot_id: UUID
    previous_snapshot_id: UUID | None
    rows: list[DiffRowOut]
```

- [ ] **Step 2: Extend `backend/app/services/snapshot.py`** — add methods for publish + archive + diff

Append to the class (after `compute`):

```python
    def publish(self, snapshot_id: UUID, published_by: UUID | None, notes: str | None) -> dict:
        return self._snapshots.publish(snapshot_id, published_by=published_by, notes=notes)

    def archive(self, snapshot_id: UUID) -> dict:
        return self._snapshots.archive(snapshot_id)

    def list(self, statuses: list[str] | None = None, limit: int = 50) -> list[dict]:
        return self._snapshots.list_snapshots(statuses=statuses, limit=limit)

    def diff_against_latest_published(self, snapshot_id: UUID) -> dict:
        """Return (previous_snapshot_id, [(iso3, segment, new_score, previous_score, delta), ...]).
        `previous_snapshot_id` is None on the very first publish."""
        current_rows = self._snapshots.country_scores_for(snapshot_id)
        previous = self._snapshots.latest_published_snapshot()

        previous_id = previous["id"] if previous else None
        previous_rows = (
            self._snapshots.country_scores_for(UUID(previous["id"])) if previous else []
        )

        previous_by_iso3 = {r["iso3"]: r for r in previous_rows}

        diff_rows = []
        for cur in sorted(current_rows, key=lambda r: r["iso3"]):
            prev = previous_by_iso3.get(cur["iso3"])
            prev_score = float(prev["final_score"]) if prev else None
            new_score = float(cur["final_score"])
            delta = new_score - prev_score if prev_score is not None else None
            diff_rows.append({
                "iso3": cur["iso3"],
                "segment": cur["segment"],
                "new_score": new_score,
                "previous_score": prev_score,
                "delta": delta,
            })

        return {
            "snapshot_id": snapshot_id,
            "previous_snapshot_id": UUID(previous_id) if previous_id else None,
            "rows": diff_rows,
        }
```

Also update the `SnapshotRepoProtocol` (at module top) to include the methods we're now calling:

Find:
```python
class SnapshotRepoProtocol(Protocol):
    def create_draft(self, draft: DraftSnapshotCreate) -> UUID: ...
    def wipe_draft_scores(self, snapshot_id: UUID) -> None: ...
    def insert_country_scores(self, snapshot_id: UUID, rows: list[CountryScoreRow]) -> int: ...
    def insert_driver_scores(self, snapshot_id: UUID, rows: list[DriverScoreRow]) -> int: ...
```

Replace with:
```python
class SnapshotRepoProtocol(Protocol):
    def create_draft(self, draft: DraftSnapshotCreate) -> UUID: ...
    def wipe_draft_scores(self, snapshot_id: UUID) -> None: ...
    def insert_country_scores(self, snapshot_id: UUID, rows: list[CountryScoreRow]) -> int: ...
    def insert_driver_scores(self, snapshot_id: UUID, rows: list[DriverScoreRow]) -> int: ...
    def publish(self, snapshot_id: UUID, published_by: UUID | None, notes: str | None) -> dict: ...
    def archive(self, snapshot_id: UUID) -> dict: ...
    def list_snapshots(self, statuses: list[str] | None, limit: int) -> list[dict]: ...
    def latest_published_snapshot(self) -> dict | None: ...
    def country_scores_for(self, snapshot_id: UUID) -> list[dict]: ...
```

- [ ] **Step 3: Add routes to `backend/app/api/admin.py`**

Add these imports at the top of the file (keep existing imports):

```python
from datetime import date as _date
from uuid import UUID
from app.repositories.raw_observations import RawObservationRepository
from app.repositories.segment import SegmentRepository
from app.repositories.snapshot import SnapshotRepository
from app.repositories.model_version import ModelVersionRepository
from app.schemas.snapshot import (
    ComputeSummaryOut,
    CreateSnapshotRequest,
    DiffOut,
    DiffRowOut,
    PublishRequest,
    SnapshotOut,
)
from app.services.snapshot import SnapshotService
```

Then append these route handlers at the end of the file:

```python
def _snapshot_service() -> SnapshotService:
    client = service_client()
    return SnapshotService(
        obs_repo=RawObservationRepository(client),
        model_repo=ModelVersionRepository(client),
        snapshot_repo=SnapshotRepository(client),
        segment_repo=SegmentRepository(client),
    )


@router.post("/snapshots", response_model=SnapshotOut, status_code=status.HTTP_201_CREATED)
def create_snapshot(
    req: CreateSnapshotRequest,
    user: CurrentUser = Depends(_require_internal),
) -> SnapshotOut:
    service = _snapshot_service()
    snapshot_id = service.create_draft(
        name=req.name,
        as_of_date=req.as_of_date,
        model_version_high=req.model_version_high,
        model_version_low=req.model_version_low,
        model_version_nodata=req.model_version_nodata,
        created_by=user.user_id,
    )
    row = SnapshotRepository(service_client()).get(snapshot_id)
    return SnapshotOut(**row)


@router.post("/snapshots/{snapshot_id}/compute", response_model=ComputeSummaryOut)
def compute_snapshot(
    snapshot_id: UUID,
    user: CurrentUser = Depends(_require_internal),
) -> ComputeSummaryOut:
    service = _snapshot_service()
    # Repopulate the service's in-memory draft cache from the persisted row.
    row = SnapshotRepository(service_client()).get(snapshot_id)
    if row["status"] != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="snapshot is not a draft")
    service._drafts[snapshot_id] = _DraftSnapshotFromDb(row)  # noqa: SLF001
    result = service.compute(snapshot_id)
    return ComputeSummaryOut(**result.__dict__)


@router.get("/snapshots", response_model=list[SnapshotOut])
def list_snapshots(
    user: CurrentUser = Depends(_require_internal),
) -> list[SnapshotOut]:
    service = _snapshot_service()
    rows = service.list()
    return [SnapshotOut(**r) for r in rows]


@router.get("/snapshots/{snapshot_id}/diff", response_model=DiffOut)
def diff_snapshot(
    snapshot_id: UUID,
    user: CurrentUser = Depends(_require_internal),
) -> DiffOut:
    service = _snapshot_service()
    d = service.diff_against_latest_published(snapshot_id)
    return DiffOut(
        snapshot_id=d["snapshot_id"],
        previous_snapshot_id=d["previous_snapshot_id"],
        rows=[DiffRowOut(**r) for r in d["rows"]],
    )


@router.post("/snapshots/{snapshot_id}/publish", response_model=SnapshotOut)
def publish_snapshot(
    snapshot_id: UUID,
    req: PublishRequest,
    user: CurrentUser = Depends(_require_internal),
) -> SnapshotOut:
    service = _snapshot_service()
    row = service.publish(snapshot_id, published_by=user.user_id, notes=req.notes)
    return SnapshotOut(**row)


@router.post("/snapshots/{snapshot_id}/archive", response_model=SnapshotOut)
def archive_snapshot(
    snapshot_id: UUID,
    user: CurrentUser = Depends(_require_internal),
) -> SnapshotOut:
    service = _snapshot_service()
    row = service.archive(snapshot_id)
    return SnapshotOut(**row)


# Helper to reconstruct the draft config from a persisted row for compute().
from app.repositories.snapshot import DraftSnapshotCreate as _DraftSnapshotCreate


def _DraftSnapshotFromDb(row: dict) -> _DraftSnapshotCreate:
    return _DraftSnapshotCreate(
        name=row["name"],
        as_of_date=_date.fromisoformat(row["as_of_date"]),
        model_version_high=UUID(row["model_version_high"]) if row.get("model_version_high") else None,
        model_version_low=UUID(row["model_version_low"]) if row.get("model_version_low") else None,
        model_version_nodata=UUID(row["model_version_nodata"]) if row.get("model_version_nodata") else None,
        created_by=UUID(row["created_by"]) if row.get("created_by") else None,
    )
```

- [ ] **Step 4: Smoke-check routes + run existing tests**

```bash
cd backend
./.venv/Scripts/python.exe -c "from app.main import create_app; app = create_app(); print('snapshot routes:', sorted([r.path for r in app.routes if hasattr(r, 'path') and 'snapshot' in r.path]))"
./.venv/Scripts/python.exe -m pytest -v 2>&1 | tail -5
```

Expected output includes all 6 snapshot routes: `/admin/snapshots`, `/admin/snapshots/{snapshot_id}/compute`, `/admin/snapshots/{snapshot_id}/diff`, `/admin/snapshots/{snapshot_id}/publish`, `/admin/snapshots/{snapshot_id}/archive`.

Pytest should still show 37 passed.

- [ ] **Step 5: Commit + push**

```bash
cd ..
git add backend/app/schemas/snapshot.py backend/app/services/snapshot.py backend/app/api/admin.py
git commit -m "feat(api): admin snapshot endpoints — create/compute/list/diff/publish/archive"
git push
```

---

## Task 9: CLI script for snapshot lifecycle

**Files:**
- Create: `backend/scripts/run_snapshot.py`

Purpose: a one-shot helper to exercise the lifecycle end-to-end against the dev DB without boot­ing the HTTP server. Useful for the manual smoke (Task 10) and day-to-day dev.

- [ ] **Step 1: Create the file**

```python
"""CLI to create + compute + (optionally) publish a draft snapshot.

Usage (from repo root, venv activated):
    python backend/scripts/run_snapshot.py create --name 2026-Q2 --as-of 2022-12-31
    python backend/scripts/run_snapshot.py compute <snapshot_id>
    python backend/scripts/run_snapshot.py diff    <snapshot_id>
    python backend/scripts/run_snapshot.py publish <snapshot_id>

Auto-picks the active model_version per segment (HIGH, LOW) from model_versions
unless overridden via --model-high / --model-low.
"""
from __future__ import annotations
import argparse
import json
from datetime import date
from uuid import UUID

from app.core.supabase import service_client
from app.repositories.model_version import ModelVersionRepository
from app.repositories.raw_observations import RawObservationRepository
from app.repositories.segment import SegmentRepository
from app.repositories.snapshot import SnapshotRepository
from app.services.snapshot import SnapshotService


def _service() -> SnapshotService:
    client = service_client()
    return SnapshotService(
        obs_repo=RawObservationRepository(client),
        model_repo=ModelVersionRepository(client),
        snapshot_repo=SnapshotRepository(client),
        segment_repo=SegmentRepository(client),
    )


def _latest_active_model_per_segment() -> dict[str, UUID]:
    client = service_client()
    resp = (
        client.table("model_versions")
        .select("id, segment, trained_at")
        .eq("status", "active")
        .order("trained_at", desc=True)
        .execute()
    )
    out: dict[str, UUID] = {}
    for row in resp.data:
        out.setdefault(row["segment"], UUID(row["id"]))
    return out


def cmd_create(args: argparse.Namespace) -> None:
    models = _latest_active_model_per_segment()
    mv_high = UUID(args.model_high) if args.model_high else models.get("HIGH")
    mv_low = UUID(args.model_low) if args.model_low else models.get("LOW")
    mv_nodata = UUID(args.model_nodata) if args.model_nodata else models.get("NODATA")

    service = _service()
    snapshot_id = service.create_draft(
        name=args.name,
        as_of_date=date.fromisoformat(args.as_of),
        model_version_high=mv_high,
        model_version_low=mv_low,
        model_version_nodata=mv_nodata,
        created_by=None,
    )
    print(f"Created draft snapshot: {snapshot_id}")
    print(f"  HIGH model:   {mv_high}")
    print(f"  LOW model:    {mv_low}")
    print(f"  NODATA model: {mv_nodata}")


def cmd_compute(args: argparse.Namespace) -> None:
    service = _service()
    row = SnapshotRepository(service_client()).get(UUID(args.snapshot_id))
    # Re-hydrate in-memory draft cache (service is stateless across CLI runs).
    from app.repositories.snapshot import DraftSnapshotCreate
    service._drafts[UUID(args.snapshot_id)] = DraftSnapshotCreate(  # noqa: SLF001
        name=row["name"],
        as_of_date=date.fromisoformat(row["as_of_date"]),
        model_version_high=UUID(row["model_version_high"]) if row.get("model_version_high") else None,
        model_version_low=UUID(row["model_version_low"]) if row.get("model_version_low") else None,
        model_version_nodata=UUID(row["model_version_nodata"]) if row.get("model_version_nodata") else None,
        created_by=UUID(row["created_by"]) if row.get("created_by") else None,
    )
    result = service.compute(UUID(args.snapshot_id))
    print(json.dumps(result.__dict__, indent=2, default=str))


def cmd_diff(args: argparse.Namespace) -> None:
    service = _service()
    d = service.diff_against_latest_published(UUID(args.snapshot_id))
    rows = d["rows"]
    print(f"previous_snapshot_id: {d['previous_snapshot_id']}")
    print(f"rows: {len(rows)}")
    by_abs_delta = sorted(
        [r for r in rows if r["delta"] is not None],
        key=lambda r: abs(r["delta"]),
        reverse=True,
    )
    print("\nTop 10 movers (by |delta|):")
    print(f"  {'ISO3':<5} {'segment':<7} {'new':>10} {'prev':>10} {'delta':>10}")
    for r in by_abs_delta[:10]:
        print(f"  {r['iso3']:<5} {r['segment']:<7} {r['new_score']:>10.3f} {r['previous_score']:>10.3f} {r['delta']:>+10.3f}")


def cmd_publish(args: argparse.Namespace) -> None:
    service = _service()
    row = service.publish(UUID(args.snapshot_id), published_by=None, notes=args.notes)
    print(json.dumps(row, indent=2, default=str))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("create")
    pc.add_argument("--name", required=True)
    pc.add_argument("--as-of", required=True, help="YYYY-MM-DD")
    pc.add_argument("--model-high", default=None)
    pc.add_argument("--model-low", default=None)
    pc.add_argument("--model-nodata", default=None)
    pc.set_defaults(func=cmd_create)

    pco = sub.add_parser("compute")
    pco.add_argument("snapshot_id")
    pco.set_defaults(func=cmd_compute)

    pd = sub.add_parser("diff")
    pd.add_argument("snapshot_id")
    pd.set_defaults(func=cmd_diff)

    pp = sub.add_parser("publish")
    pp.add_argument("snapshot_id")
    pp.add_argument("--notes", default=None)
    pp.set_defaults(func=cmd_publish)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke-import**

```bash
cd backend
./.venv/Scripts/python.exe -c "import importlib.util; spec = importlib.util.spec_from_file_location('rs', 'scripts/run_snapshot.py'); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); print('imports ok')"
```

Expected: `imports ok`.

- [ ] **Step 3: Commit + push**

```bash
cd ..
git add backend/scripts/run_snapshot.py
git commit -m "feat(scripts): run_snapshot CLI — create/compute/diff/publish end-to-end"
git push
```

---

## Task 10: Manual end-to-end smoke (user)

Not a code task — the user exercises the full lifecycle against the dev DB.

- [ ] **Step 1: Create the first draft**

```powershell
cd "C:\Users\APR\OneDrive - Anchor Point Risk (Pty) Ltd\Desktop\VS_CODE_REPOSITORY\country-risk-model\backend"
.\.venv\Scripts\python.exe scripts\run_snapshot.py create --name "2022-FY" --as-of 2022-12-31
```

Expected: prints `Created draft snapshot: <uuid>` plus the model version IDs picked for HIGH/LOW.

**Save the uuid** — you'll need it for the next steps. Call it `$SID` in your head.

- [ ] **Step 2: Compute scores**

```powershell
.\.venv\Scripts\python.exe scripts\run_snapshot.py compute <SID>
```

Expected JSON result (approximate):
```
{
  "snapshot_id": "<SID>",
  "countries_scored": 40-80,
  "countries_skipped_missing_data": 80-120,
  "countries_skipped_no_model": 0,
  "countries_skipped_no_segment": 0,
  ...
}
```

Most countries will be skipped because Plan 3 only ingested 5 of our 14 variables — trained models need all of them. That's expected for this first pass; `countries_skipped_missing_data` is the headline number.

If `countries_scored` is 0, something's off — paste the output.

- [ ] **Step 3: Diff against latest published** (will be empty since nothing's published yet)

```powershell
.\.venv\Scripts\python.exe scripts\run_snapshot.py diff <SID>
```

Expected: `previous_snapshot_id: None`, rows: N (= countries_scored), all `delta` fields empty.

- [ ] **Step 4: Verify in Supabase Studio**

Open https://supabase.com/dashboard/project/bqwnwuncwwiicgvfnuzv/sql/new and run:

```sql
SELECT status, name, as_of_date, created_at FROM score_snapshots ORDER BY created_at DESC LIMIT 5;

SELECT snapshot_id, count(*) AS n_countries, min(final_score) AS min_score, max(final_score) AS max_score
FROM country_scores
GROUP BY snapshot_id;

SELECT count(*) FROM driver_scores WHERE snapshot_id = '<SID>';
```

Expected:
- 1 row in `score_snapshots` with status='draft'
- 1 row per snapshot in `country_scores` aggregation, with N = countries_scored
- driver_scores count ≈ `countries_scored × (len(quant) + len(qual))` — roughly `countries_scored × 14`.

- [ ] **Step 5: Publish**

```powershell
.\.venv\Scripts\python.exe scripts\run_snapshot.py publish <SID> --notes "first official publish"
```

Expected JSON: `status: "published"` + `published_at: <timestamp>`.

- [ ] **Step 6: Verify immutability (manual test)**

In Supabase Studio SQL editor, try to UPDATE a published score row:

```sql
UPDATE country_scores
SET final_score = 999.0
WHERE snapshot_id = '<SID>'
LIMIT 1;
```

Expected: `ERROR: cannot modify rows of a published snapshot (...)`. ✅ means the trigger works.

Then try an invalid status transition:

```sql
UPDATE score_snapshots SET status = 'draft' WHERE id = '<SID>';
```

Expected: `ERROR: invalid snapshot status transition: published → draft`. ✅

- [ ] **Step 7: Reply with the snapshot_id, compute result JSON, and confirmation that both immutability tests raised the expected errors.**

---

## Task 11: Tag plan-4-snapshot-lifecycle

- [ ] **Step 1: Final test run**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest -v
```

Expected: 37 passed, 5 deselected. No failures.

- [ ] **Step 2: Tag**

```bash
cd ..
git tag -a plan-4-snapshot-lifecycle -m "Plan 4 complete: draft/compute/diff/publish + immutability triggers + audit log"
git push --tags
```

- [ ] **Step 3: Confirm on GitHub tags page**

Visit https://github.com/henrye1/country-risk-model/tags. `plan-4-snapshot-lifecycle` should appear.

---

## Validation Checklist (end-of-plan)

Tick these before declaring Plan 4 done:

- [ ] Migrations `_001_score_snapshots`, `_002_score_triggers`, `_003_audit_log` applied; all four tables visible in Studio with RLS enabled.
- [ ] `pytest -v`: 37 passed, 0 failures.
- [ ] `run_snapshot.py create/compute/diff/publish` commands all work end-to-end.
- [ ] Attempting to UPDATE a published `country_scores` row in Studio raises the immutability error.
- [ ] Attempting to revert status from `published` to `draft` raises the transition error.
- [ ] Tag `plan-4-snapshot-lifecycle` pushed.

When all ticked: ready for **Plan 5 — Public read API & country UI**, which surfaces published snapshots to PD/LGD consumers and to the React frontend.
