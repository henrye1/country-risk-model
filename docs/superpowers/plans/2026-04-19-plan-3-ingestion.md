# Plan 3 — Data Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the ingestion backbone for the Country Risk Model. After this plan, an authenticated internal analyst can call `POST /admin/ingest/world-bank` to pull annual values for a curated set of World Bank / WGI indicators into the `raw_observations` table. This replaces the 2011-only prototype data with fresh, year-by-year, reproducible input for future retraining.

**Architecture:** One new migration adds two append-only tables (`raw_observations`, `data_uploads`). A new `app/ingestion/` package holds an `httpx`-based World Bank API client. A new FastAPI admin router (`/admin/...`) authenticates via the existing JWT dependency + a role guard for internal users only. The ingestion service orchestrates: fetch from WB → validate → bulk-insert into `raw_observations` under a single `data_uploads` parent row. Domain code remains pure Python; the HTTP client is tested with `respx` (recorded fakes) and a slow `@pytest.mark.integration` test hits the live WB API.

**Tech Stack:** Python 3.12 (FastAPI, httpx, Pydantic, pytest, respx), Supabase Postgres (new tables), World Bank Open Data API (free, no key).

**Scope (what this plan does NOT cover):**

- **Manual CSV uploads.** Out of scope for Plan 3 per user request (API-first). A follow-on plan will add the upload flow.
- **Multi-year aggregates.** The 14 variables seeded in Plan 1 include some multi-year metrics (e.g. `dcpi_5_adj` = 5-year inflation average). Plan 3 handles **single-year** WB indicators only. Variables requiring multi-year computation are deferred — the config below lists only the 6 variables with direct single-year mappings.
- **Frontend admin UI.** No new React screens. Ingestion is called via API directly (or curl/Postman) for now.
- **WGI separate endpoint.** WGI indicators (Rule of Law, Political Stability, Doing Business) are served by the same `api.worldbank.org` API family as other World Bank indicators, so a single HTTP client covers both.

**Precondition:** Plan 2 is complete (tag `plan-2-scoring-engine`). Two trained models are persisted. Repo is at `C:/Users/APR/OneDrive - Anchor Point Risk (Pty) Ltd/Desktop/VS_CODE_REPOSITORY/country-risk-model/`.

---

## File Structure After This Plan

```
country-risk-model/
├── backend/
│   ├── app/
│   │   ├── ingestion/                      # NEW package
│   │   │   ├── __init__.py
│   │   │   ├── world_bank.py               # httpx-based WB API client (pure fetch)
│   │   │   └── variable_sources.py         # our variable codes → WB indicator IDs
│   │   ├── repositories/
│   │   │   └── raw_observations.py         # NEW: batch insert + data_uploads row
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   └── ingestion.py                # NEW: orchestrate fetch → persist
│   │   ├── api/
│   │   │   └── admin.py                    # NEW: /admin router (role-gated)
│   │   └── schemas/
│   │       └── ingestion.py                # NEW: pydantic request/response models
│   └── tests/
│       ├── ingestion/                      # NEW
│       │   ├── __init__.py
│       │   ├── test_world_bank_client.py   # respx-mocked unit tests
│       │   └── test_ingestion_service.py   # service tests with stub repo
│       ├── api/                            # NEW subfolder
│       │   ├── __init__.py
│       │   └── test_admin_ingest.py        # FastAPI route tests
│       └── integration/
│           └── test_world_bank_live.py     # live-network @integration test
└── supabase/
    └── migrations/
        └── 20260419000005_raw_observations.sql   # NEW
```

Design principles:
- `app/ingestion/world_bank.py` knows HTTP and JSON. Nothing else. No Supabase. No FastAPI.
- `app/services/ingestion.py` wires the HTTP client to the repository. It's where the business logic lives (e.g. skip rows with null values, associate ingested batch with a `data_upload_id`). This file is testable with a fake HTTP client + a fake repository.
- `app/repositories/raw_observations.py` wraps Supabase table calls. No business logic.
- `app/api/admin.py` is thin: auth → call service → return result.

---

## Task 1: Migration 5 — raw_observations and data_uploads tables

**Files:**
- Create: `supabase/migrations/20260419000005_raw_observations.sql`

- [ ] **Step 1: Write the migration**

```sql
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
```

- [ ] **Step 2: Apply**

```bash
/c/Users/APR/scoop/shims/supabase.exe db push --linked
```

Expected: `Applying migration 20260419000005_raw_observations.sql... Finished supabase db push.`

- [ ] **Step 3: Re-run to verify**

```bash
/c/Users/APR/scoop/shims/supabase.exe db push --linked
```

Expected: `Remote database is up to date.`

- [ ] **Step 4: Commit + push**

```bash
cd "C:/Users/APR/OneDrive - Anchor Point Risk (Pty) Ltd/Desktop/VS_CODE_REPOSITORY/country-risk-model/"
git add supabase/migrations/20260419000005_raw_observations.sql
git commit -m "feat(db): raw_observations + data_uploads tables for ingestion"
git push
```

---

## Task 2: Variable → World Bank indicator mapping

**Files:**
- Create: `backend/app/ingestion/__init__.py`
- Create: `backend/app/ingestion/variable_sources.py`
- Create: `backend/tests/ingestion/__init__.py`

- [ ] **Step 1: Create package markers**

```bash
cd "C:/Users/APR/OneDrive - Anchor Point Risk (Pty) Ltd/Desktop/VS_CODE_REPOSITORY/country-risk-model/"
mkdir -p backend/app/ingestion backend/tests/ingestion
touch backend/app/ingestion/__init__.py backend/tests/ingestion/__init__.py
```

- [ ] **Step 2: Create `backend/app/ingestion/variable_sources.py`**

```python
"""Mapping: our internal variable codes → external data source identifiers.

Only single-year, directly-mapped variables are listed here. Multi-year aggregates
(e.g. 5-year inflation averages) will be computed in a later plan and aren't in
scope for Plan 3.

The tuple is (source, indicator_id). `source` is one of our `observation_source`
enum values. `indicator_id` for source='WB' or source='WGI' is the World Bank
Open Data indicator code.
"""
from __future__ import annotations
from typing import Literal

SourceTag = Literal["WB", "WGI"]

# Single-year mappings. Extend this dict when adding indicators.
WORLD_BANK_SOURCES: dict[str, tuple[SourceTag, str]] = {
    "gdp_capita":          ("WB",  "NY.GDP.PCAP.CD"),      # GDP per capita (current US$)
    "rol":                 ("WGI", "RL.EST"),              # WGI: Rule of Law, estimate
    "pr":                  ("WGI", "PV.EST"),              # WGI: Political Stability estimate
    "db":                  ("WB",  "IC.BUS.EASE.XQ"),      # Ease of doing business (discontinued 2022, historical still available)
    "cof":                 ("WB",  "FR.INR.LEND"),         # Lending interest rate (%)
    "debt_service_ratio":  ("WB",  "DT.TDS.DECT.EX.ZS"),   # Total debt service (% of exports of goods, services and primary income)
}


def indicator_for(variable_code: str) -> tuple[SourceTag, str]:
    """Return (source, indicator_id) for a variable code, or raise KeyError."""
    if variable_code not in WORLD_BANK_SOURCES:
        raise KeyError(f"no World Bank mapping for variable '{variable_code}'")
    return WORLD_BANK_SOURCES[variable_code]


def variables_available_via_api() -> tuple[str, ...]:
    """All variable codes currently fetchable via the World Bank API."""
    return tuple(WORLD_BANK_SOURCES.keys())
```

- [ ] **Step 3: Smoke test**

```bash
cd backend
./.venv/Scripts/python.exe -c "from app.ingestion.variable_sources import indicator_for, variables_available_via_api; print(indicator_for('gdp_capita')); print(variables_available_via_api())"
```

Expected output:
```
('WB', 'NY.GDP.PCAP.CD')
('gdp_capita', 'rol', 'pr', 'db', 'cof', 'debt_service_ratio')
```

- [ ] **Step 4: Commit + push**

```bash
cd ..
git add backend/app/ingestion backend/tests/ingestion
git commit -m "feat(ingestion): variable_sources — map internal codes to WB indicators"
git push
```

---

## Task 3: World Bank HTTP client (TDD with respx)

**Files:**
- Create: `backend/app/ingestion/world_bank.py`
- Create: `backend/tests/ingestion/test_world_bank_client.py`

Background: the World Bank Open Data API returns a paginated response shape like:

```json
[
  {"page": 1, "pages": 2, "per_page": 50, "total": 65, ...},
  [
    {"indicator": {"id": "NY.GDP.PCAP.CD", "value": "GDP per capita (current US$)"},
     "country":   {"id": "US", "value": "United States"},
     "countryiso3code": "USA",
     "date": "2021",
     "value": 70248.6,
     "unit": "", "obs_status": "", "decimal": 1},
    ...
  ]
]
```

We'll keep the client minimal: it fetches one indicator for all countries for one year, paginates, returns `dict[iso3_str, float | None]`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/ingestion/test_world_bank_client.py
from __future__ import annotations
import httpx
import pytest
import respx

from app.ingestion.world_bank import WorldBankClient, WorldBankError


@pytest.fixture
def client() -> WorldBankClient:
    return WorldBankClient(base_url="https://api.worldbank.org/v2", timeout_seconds=5.0)


@respx.mock
def test_fetch_indicator_for_year_returns_iso3_to_value(client):
    respx.get("https://api.worldbank.org/v2/country/all/indicator/NY.GDP.PCAP.CD").respond(
        200,
        json=[
            {"page": 1, "pages": 1, "per_page": 500, "total": 2, "sourceid": "2"},
            [
                {"indicator": {"id": "NY.GDP.PCAP.CD", "value": "GDP per capita"},
                 "country": {"id": "US", "value": "United States"},
                 "countryiso3code": "USA", "date": "2021",
                 "value": 70248.6258893, "unit": "", "obs_status": "", "decimal": 1},
                {"indicator": {"id": "NY.GDP.PCAP.CD", "value": "GDP per capita"},
                 "country": {"id": "ZA", "value": "South Africa"},
                 "countryiso3code": "ZAF", "date": "2021",
                 "value": 6994.2, "unit": "", "obs_status": "", "decimal": 1},
            ],
        ],
    )

    result = client.fetch_indicator_for_year(indicator_id="NY.GDP.PCAP.CD", year=2021)

    assert result == {"USA": 70248.6258893, "ZAF": 6994.2}


@respx.mock
def test_fetch_indicator_handles_null_values(client):
    respx.get("https://api.worldbank.org/v2/country/all/indicator/NY.GDP.PCAP.CD").respond(
        200,
        json=[
            {"page": 1, "pages": 1, "per_page": 500, "total": 1, "sourceid": "2"},
            [
                {"indicator": {"id": "NY.GDP.PCAP.CD", "value": "GDP per capita"},
                 "country": {"id": "EX", "value": "Example"},
                 "countryiso3code": "EXX", "date": "2021",
                 "value": None, "unit": "", "obs_status": "", "decimal": 1},
            ],
        ],
    )

    result = client.fetch_indicator_for_year(indicator_id="NY.GDP.PCAP.CD", year=2021)

    assert result == {"EXX": None}


@respx.mock
def test_fetch_indicator_follows_pagination(client):
    respx.get("https://api.worldbank.org/v2/country/all/indicator/NY.GDP.PCAP.CD", params__contains={"page": "1"}).respond(
        200,
        json=[
            {"page": 1, "pages": 2, "per_page": 1, "total": 2, "sourceid": "2"},
            [{"countryiso3code": "USA", "date": "2021", "value": 70248.6,
              "indicator": {"id": "NY.GDP.PCAP.CD", "value": ""},
              "country": {"id": "US", "value": ""}, "unit": "", "obs_status": "", "decimal": 1}],
        ],
    )
    respx.get("https://api.worldbank.org/v2/country/all/indicator/NY.GDP.PCAP.CD", params__contains={"page": "2"}).respond(
        200,
        json=[
            {"page": 2, "pages": 2, "per_page": 1, "total": 2, "sourceid": "2"},
            [{"countryiso3code": "ZAF", "date": "2021", "value": 6994.2,
              "indicator": {"id": "NY.GDP.PCAP.CD", "value": ""},
              "country": {"id": "ZA", "value": ""}, "unit": "", "obs_status": "", "decimal": 1}],
        ],
    )

    result = client.fetch_indicator_for_year(indicator_id="NY.GDP.PCAP.CD", year=2021)

    assert result == {"USA": 70248.6, "ZAF": 6994.2}


@respx.mock
def test_fetch_indicator_raises_on_http_error(client):
    respx.get("https://api.worldbank.org/v2/country/all/indicator/NY.GDP.PCAP.CD").respond(500, text="server error")

    with pytest.raises(WorldBankError, match="status 500"):
        client.fetch_indicator_for_year(indicator_id="NY.GDP.PCAP.CD", year=2021)


@respx.mock
def test_fetch_indicator_raises_on_invalid_shape(client):
    respx.get("https://api.worldbank.org/v2/country/all/indicator/NY.GDP.PCAP.CD").respond(
        200, json={"this_is_not": "an_array"}
    )

    with pytest.raises(WorldBankError, match="unexpected response shape"):
        client.fetch_indicator_for_year(indicator_id="NY.GDP.PCAP.CD", year=2021)
```

- [ ] **Step 2: Run — confirm failure**

```bash
cd backend
source .venv/Scripts/activate  # or use ./.venv/Scripts/python.exe directly if on PowerShell
pytest tests/ingestion/test_world_bank_client.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.ingestion.world_bank'`.

- [ ] **Step 3: Implement `backend/app/ingestion/world_bank.py`**

```python
"""Minimal World Bank Open Data API client.

Fetches one indicator for all countries for one year, follows pagination,
returns a plain dict mapping iso3 country codes → value (float or None).

No Supabase, no FastAPI. Only httpx + stdlib.
"""
from __future__ import annotations
from dataclasses import dataclass

import httpx


class WorldBankError(RuntimeError):
    """Raised when the WB API returns an unexpected response or non-2xx status."""


@dataclass
class WorldBankClient:
    base_url: str = "https://api.worldbank.org/v2"
    timeout_seconds: float = 30.0
    per_page: int = 500

    def fetch_indicator_for_year(
        self,
        indicator_id: str,
        year: int,
    ) -> dict[str, float | None]:
        """Return {iso3: value} for every country with a reported observation.

        Countries absent from the response are simply not in the returned dict.
        Values reported as null by the WB API are kept as None in the dict.
        """
        out: dict[str, float | None] = {}
        page = 1
        while True:
            params = {
                "format": "json",
                "date": str(year),
                "per_page": str(self.per_page),
                "page": str(page),
            }
            url = f"{self.base_url}/country/all/indicator/{indicator_id}"
            try:
                with httpx.Client(timeout=self.timeout_seconds) as http:
                    resp = http.get(url, params=params)
            except httpx.HTTPError as exc:
                raise WorldBankError(f"HTTP error fetching {indicator_id}: {exc}") from exc

            if resp.status_code != 200:
                raise WorldBankError(
                    f"World Bank API returned status {resp.status_code} for {indicator_id}"
                )

            try:
                payload = resp.json()
            except Exception as exc:
                raise WorldBankError(f"could not parse JSON from WB response: {exc}") from exc

            if not isinstance(payload, list) or len(payload) != 2 or not isinstance(payload[1], list):
                raise WorldBankError(f"unexpected response shape for {indicator_id}")

            meta, rows = payload
            for row in rows:
                iso3 = row.get("countryiso3code")
                if not iso3:
                    continue
                val = row.get("value")
                out[iso3] = float(val) if isinstance(val, (int, float)) else None

            total_pages = int(meta.get("pages", 1))
            if page >= total_pages:
                break
            page += 1
        return out
```

- [ ] **Step 4: Run — should pass**

```bash
pytest tests/ingestion/test_world_bank_client.py -v
```

Expected: `5 passed`.

- [ ] **Step 5: Commit + push**

```bash
cd ..
git add backend/app/ingestion/world_bank.py backend/tests/ingestion/test_world_bank_client.py
git commit -m "feat(ingestion): World Bank API client with pagination (TDD)"
git push
```

---

## Task 4: Raw observations repository

**Files:**
- Create: `backend/app/repositories/raw_observations.py`

No TDD here — this is pure Supabase plumbing. It's exercised by the ingestion service test (Task 6) and the admin endpoint test (Task 8).

- [ ] **Step 1: Create the file**

```python
# backend/app/repositories/raw_observations.py
"""Persist raw observations + data_uploads metadata via Supabase.

Called from the ingestion service (admin path). Uses whichever `supabase.Client`
is provided — typically `service_client()` since writes to these tables are
restricted to service_role by RLS.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from supabase import Client


@dataclass
class ObservationRow:
    iso3: str
    variable_code: str
    year: int
    value: float | None
    source: str


class RawObservationRepository:
    def __init__(self, client: Client) -> None:
        self._client = client

    def create_upload(
        self,
        source: str,
        file_name: str | None,
        notes: str | None,
        uploaded_by: UUID | None,
    ) -> UUID:
        """Create a data_uploads parent row. Returns its id.

        `row_count` is 0 here; it's patched after observations are inserted.
        """
        payload: dict[str, Any] = {
            "source": source,
            "file_name": file_name,
            "notes": notes,
            "row_count": 0,
        }
        if uploaded_by is not None:
            payload["uploaded_by"] = str(uploaded_by)
        resp = self._client.table("data_uploads").insert(payload).execute()
        return UUID(resp.data[0]["id"])

    def insert_observations(
        self,
        rows: list[ObservationRow],
        upload_id: UUID,
        ingested_by: UUID | None,
    ) -> int:
        """Batch-insert observations and update the upload's row_count. Returns n inserted."""
        if not rows:
            return 0
        payload_rows = [
            {
                "iso3": r.iso3,
                "variable_code": r.variable_code,
                "year": r.year,
                "value": r.value,
                "source": r.source,
                "upload_id": str(upload_id),
                "ingested_by": str(ingested_by) if ingested_by else None,
            }
            for r in rows
        ]
        # Supabase-py currently inserts up to ~1000 per batch; chunk for safety.
        CHUNK = 500
        inserted = 0
        for i in range(0, len(payload_rows), CHUNK):
            chunk = payload_rows[i : i + CHUNK]
            resp = self._client.table("raw_observations").insert(chunk).execute()
            inserted += len(resp.data)
        self._client.table("data_uploads").update({"row_count": inserted}).eq(
            "id", str(upload_id)
        ).execute()
        return inserted

    def known_iso3_codes(self) -> set[str]:
        """Return the iso3 codes present in the `countries` reference table.

        The ingestion service uses this to skip WB rows whose country isn't seeded
        (e.g. aggregate codes like 'WLD', 'AFE') — raw_observations has a FK on iso3.
        """
        resp = self._client.table("countries").select("iso3").execute()
        return {row["iso3"] for row in resp.data}
```

- [ ] **Step 2: Smoke-import test**

```bash
cd backend
./.venv/Scripts/python.exe -c "from app.repositories.raw_observations import RawObservationRepository, ObservationRow; print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Commit + push**

```bash
cd ..
git add backend/app/repositories/raw_observations.py
git commit -m "feat(backend): raw_observations repository (batch insert + upload metadata)"
git push
```

---

## Task 5: Ingestion request/response schemas

**Files:**
- Create: `backend/app/schemas/ingestion.py`

- [ ] **Step 1: Create the file**

```python
# backend/app/schemas/ingestion.py
from __future__ import annotations
from uuid import UUID
from pydantic import BaseModel, Field


class WorldBankIngestRequest(BaseModel):
    variables: list[str] = Field(min_length=1)
    year: int = Field(ge=1960, le=2100)
    notes: str | None = None


class IngestResultOut(BaseModel):
    upload_id: UUID
    source: str
    year: int
    variables_ingested: list[str]
    rows_inserted: int
    rows_skipped_unknown_country: int
    rows_skipped_null_value: int
    warnings: list[str] = Field(default_factory=list)
```

- [ ] **Step 2: Commit + push** (no standalone test; used in later tasks)

```bash
git add backend/app/schemas/ingestion.py
git commit -m "feat(backend): ingestion request/response schemas"
git push
```

---

## Task 6: Ingestion service (TDD with stubs)

**Files:**
- Create: `backend/app/services/__init__.py`
- Create: `backend/app/services/ingestion.py`
- Create: `backend/tests/ingestion/test_ingestion_service.py`

- [ ] **Step 1: Create the services package marker**

```bash
cd "C:/Users/APR/OneDrive - Anchor Point Risk (Pty) Ltd/Desktop/VS_CODE_REPOSITORY/country-risk-model/"
touch backend/app/services/__init__.py
```

- [ ] **Step 2: Write the failing test `backend/tests/ingestion/test_ingestion_service.py`**

```python
from __future__ import annotations
from uuid import UUID, uuid4

import pytest

from app.repositories.raw_observations import ObservationRow
from app.services.ingestion import (
    IngestionService,
    UnknownVariable,
)


class FakeWBClient:
    def __init__(self, payloads: dict[tuple[str, int], dict[str, float | None]]) -> None:
        self._payloads = payloads
        self.calls: list[tuple[str, int]] = []

    def fetch_indicator_for_year(self, indicator_id: str, year: int) -> dict[str, float | None]:
        self.calls.append((indicator_id, year))
        return self._payloads[(indicator_id, year)]


class FakeRepo:
    def __init__(self, known_iso3: set[str]) -> None:
        self._known = known_iso3
        self.uploads: list[dict] = []
        self.observations: list[ObservationRow] = []
        self.upload_id = uuid4()

    def create_upload(self, source, file_name, notes, uploaded_by):
        self.uploads.append({"source": source, "file_name": file_name, "notes": notes, "uploaded_by": uploaded_by})
        return self.upload_id

    def insert_observations(self, rows, upload_id, ingested_by):
        assert upload_id == self.upload_id
        self.observations.extend(rows)
        return len(rows)

    def known_iso3_codes(self) -> set[str]:
        return set(self._known)


def test_ingest_world_bank_maps_variables_and_inserts_rows():
    payloads = {
        ("NY.GDP.PCAP.CD", 2021): {"USA": 70000.0, "ZAF": 6000.0, "ZZZ": 999.0},  # ZZZ = unknown
        ("RL.EST", 2021): {"USA": 1.5, "ZAF": 0.2},
    }
    wb = FakeWBClient(payloads)
    repo = FakeRepo(known_iso3={"USA", "ZAF"})
    service = IngestionService(wb_client=wb, repo=repo)

    result = service.ingest_world_bank(
        variable_codes=["gdp_capita", "rol"],
        year=2021,
        user_id=None,
        notes="test pull",
    )

    assert result.rows_inserted == 4   # (USA, ZAF) × (gdp_capita, rol)
    assert result.rows_skipped_unknown_country == 1  # ZZZ
    assert result.rows_skipped_null_value == 0
    assert sorted(result.variables_ingested) == ["gdp_capita", "rol"]
    assert result.upload_id == repo.upload_id

    # Observations carry the internal variable codes and the right source tag.
    by_var = {}
    for r in repo.observations:
        by_var.setdefault(r.variable_code, []).append(r)
    assert {r.iso3 for r in by_var["gdp_capita"]} == {"USA", "ZAF"}
    assert {r.iso3 for r in by_var["rol"]} == {"USA", "ZAF"}
    assert all(r.source == "WB" for r in by_var["gdp_capita"])
    assert all(r.source == "WGI" for r in by_var["rol"])
    assert all(r.year == 2021 for r in repo.observations)


def test_ingest_world_bank_skips_null_values():
    payloads = {
        ("NY.GDP.PCAP.CD", 2021): {"USA": None, "ZAF": 6000.0},
    }
    wb = FakeWBClient(payloads)
    repo = FakeRepo(known_iso3={"USA", "ZAF"})
    service = IngestionService(wb_client=wb, repo=repo)

    result = service.ingest_world_bank(
        variable_codes=["gdp_capita"],
        year=2021,
        user_id=None,
        notes=None,
    )

    assert result.rows_inserted == 1            # only ZAF
    assert result.rows_skipped_null_value == 1  # USA
    assert len(repo.observations) == 1
    assert repo.observations[0].iso3 == "ZAF"


def test_ingest_world_bank_raises_on_unknown_variable():
    wb = FakeWBClient({})
    repo = FakeRepo(known_iso3=set())
    service = IngestionService(wb_client=wb, repo=repo)

    with pytest.raises(UnknownVariable, match="fake_var"):
        service.ingest_world_bank(
            variable_codes=["fake_var"],
            year=2021,
            user_id=None,
            notes=None,
        )
```

- [ ] **Step 3: Run — confirm failure**

```bash
cd backend
pytest tests/ingestion/test_ingestion_service.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.services.ingestion'`.

- [ ] **Step 4: Implement `backend/app/services/ingestion.py`**

```python
"""Ingestion service: orchestrate World Bank fetch → raw_observations insert."""
from __future__ import annotations
from typing import Protocol
from uuid import UUID

from app.ingestion.variable_sources import WORLD_BANK_SOURCES
from app.repositories.raw_observations import ObservationRow
from app.schemas.ingestion import IngestResultOut


class UnknownVariable(ValueError):
    """Raised when a requested variable_code has no WB mapping."""


class WBClientProtocol(Protocol):
    def fetch_indicator_for_year(self, indicator_id: str, year: int) -> dict[str, float | None]: ...


class RawObsRepoProtocol(Protocol):
    def create_upload(self, source: str, file_name: str | None, notes: str | None, uploaded_by: UUID | None) -> UUID: ...
    def insert_observations(self, rows: list[ObservationRow], upload_id: UUID, ingested_by: UUID | None) -> int: ...
    def known_iso3_codes(self) -> set[str]: ...


class IngestionService:
    def __init__(self, wb_client: WBClientProtocol, repo: RawObsRepoProtocol) -> None:
        self._wb = wb_client
        self._repo = repo

    def ingest_world_bank(
        self,
        variable_codes: list[str],
        year: int,
        user_id: UUID | None,
        notes: str | None,
    ) -> IngestResultOut:
        # Validate all variable codes up front.
        for code in variable_codes:
            if code not in WORLD_BANK_SOURCES:
                raise UnknownVariable(f"variable '{code}' has no World Bank mapping")

        # Single parent row for the whole batch; per-variable rows rollup under it.
        # Use the first variable's source tag as the parent tag; individual rows
        # still carry their specific source (WB / WGI).
        first_source = WORLD_BANK_SOURCES[variable_codes[0]][0]
        upload_id = self._repo.create_upload(
            source=first_source,
            file_name=None,
            notes=notes,
            uploaded_by=user_id,
        )

        known_iso3 = self._repo.known_iso3_codes()

        rows: list[ObservationRow] = []
        skipped_unknown = 0
        skipped_null = 0
        warnings: list[str] = []

        for code in variable_codes:
            source_tag, indicator_id = WORLD_BANK_SOURCES[code]
            try:
                data = self._wb.fetch_indicator_for_year(indicator_id, year)
            except Exception as exc:  # world_bank.WorldBankError + network
                warnings.append(f"{code}: fetch failed — {exc}")
                continue

            for iso3, value in data.items():
                if iso3 not in known_iso3:
                    skipped_unknown += 1
                    continue
                if value is None:
                    skipped_null += 1
                    continue
                rows.append(ObservationRow(
                    iso3=iso3,
                    variable_code=code,
                    year=year,
                    value=value,
                    source=source_tag,
                ))

        inserted = self._repo.insert_observations(rows, upload_id=upload_id, ingested_by=user_id)

        return IngestResultOut(
            upload_id=upload_id,
            source=first_source,
            year=year,
            variables_ingested=list(variable_codes),
            rows_inserted=inserted,
            rows_skipped_unknown_country=skipped_unknown,
            rows_skipped_null_value=skipped_null,
            warnings=warnings,
        )
```

- [ ] **Step 5: Run — should pass**

```bash
pytest tests/ingestion/test_ingestion_service.py -v
```

Expected: `3 passed`.

- [ ] **Step 6: Commit + push**

```bash
cd ..
git add backend/app/services backend/tests/ingestion/test_ingestion_service.py
git commit -m "feat(services): ingestion orchestrator — fetch WB + persist raw_observations (TDD)"
git push
```

---

## Task 7: Role-gated admin router (FastAPI)

**Files:**
- Create: `backend/app/api/admin.py`
- Modify: `backend/app/main.py` — register router

- [ ] **Step 1: Create `backend/app/api/admin.py`**

```python
"""Admin API router — internal organisation members only."""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import get_current_user
from app.core.supabase import service_client
from app.ingestion.world_bank import WorldBankClient
from app.repositories.raw_observations import RawObservationRepository
from app.schemas.ingestion import IngestResultOut, WorldBankIngestRequest
from app.schemas.user import CurrentUser
from app.services.ingestion import IngestionService, UnknownVariable


router = APIRouter(prefix="/admin", tags=["admin"])


def _require_internal(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Role gate: the caller must belong to an organisation with status='internal'.
    We determine this by asking the service_client to read the caller's membership
    (bypasses RLS for this check).
    """
    client = service_client()
    resp = (
        client.table("memberships")
        .select("organisation_id, role, organisations(status)")
        .eq("user_id", str(user.user_id))
        .limit(1)
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="no membership")
    org_status = (resp.data[0].get("organisations") or {}).get("status")
    if org_status != "internal":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="internal only")
    return user


@router.post("/ingest/world-bank", response_model=IngestResultOut)
def ingest_world_bank(
    req: WorldBankIngestRequest,
    user: CurrentUser = Depends(_require_internal),
) -> IngestResultOut:
    client = service_client()
    repo = RawObservationRepository(client)
    wb = WorldBankClient()
    service = IngestionService(wb_client=wb, repo=repo)

    try:
        return service.ingest_world_bank(
            variable_codes=req.variables,
            year=req.year,
            user_id=user.user_id,
            notes=req.notes,
        )
    except UnknownVariable as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
```

- [ ] **Step 2: Register the router in `backend/app/main.py`**

Use the Edit tool. Find:
```python
from app.api import health, public
```

Replace with:
```python
from app.api import admin, health, public
```

Then find:
```python
    app.include_router(health.router)
    app.include_router(public.router)
```

Replace with:
```python
    app.include_router(health.router)
    app.include_router(public.router)
    app.include_router(admin.router)
```

- [ ] **Step 3: Smoke-check the app still boots**

```bash
cd backend
./.venv/Scripts/python.exe -c "from app.main import create_app; app = create_app(); print('routes:', [r.path for r in app.routes])"
```

Expected output contains `/v1/health`, `/v1/countries`, `/v1/variables`, `/admin/ingest/world-bank`.

- [ ] **Step 4: Run the unit tests — no regressions**

```bash
pytest -v
```

Expected: 21 passed, 4 deselected (previous total + no new unit tests yet from this task).

- [ ] **Step 5: Commit + push**

```bash
cd ..
git add backend/app/api/admin.py backend/app/main.py
git commit -m "feat(api): /admin router with internal-role gate + POST /admin/ingest/world-bank"
git push
```

---

## Task 8: Admin ingest endpoint — route-level tests

**Files:**
- Create: `backend/tests/api/__init__.py`
- Create: `backend/tests/api/test_admin_ingest.py`

- [ ] **Step 1: Create the package marker**

```bash
cd backend
mkdir -p tests/api
touch tests/api/__init__.py
```

- [ ] **Step 2: Write the test**

This test uses FastAPI's `TestClient` and monkey-patches both the HTTP client and the Supabase service_client to avoid any network/DB touch. We'll also sign a valid JWT so auth passes, then override `_require_internal` via dependency override to skip the membership lookup (which is tested separately via RLS manually).

```python
# backend/tests/api/test_admin_ingest.py
from __future__ import annotations
import time
import pytest
from jose import jwt
from fastapi.testclient import TestClient

JWT_SECRET = "test-jwt-secret"


def _token(user_id: str = "11111111-1111-1111-1111-111111111111") -> str:
    payload = {
        "sub": user_id,
        "email": "tester@example.com",
        "aud": "authenticated",
        "role": "authenticated",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


class _FakeWB:
    def __init__(self) -> None:
        self.payloads = {("NY.GDP.PCAP.CD", 2021): {"USA": 70000.0, "ZAF": 6000.0}}

    def fetch_indicator_for_year(self, indicator_id, year):
        return self.payloads[(indicator_id, year)]


class _FakeRepo:
    def __init__(self) -> None:
        from uuid import uuid4
        self.upload_id = uuid4()
        self.observations: list = []

    def create_upload(self, source, file_name, notes, uploaded_by):
        return self.upload_id

    def insert_observations(self, rows, upload_id, ingested_by):
        self.observations.extend(rows)
        return len(rows)

    def known_iso3_codes(self) -> set[str]:
        return {"USA", "ZAF"}


@pytest.fixture
def client(monkeypatch):
    from app.main import create_app
    from app.api import admin
    from app.schemas.user import CurrentUser
    from uuid import UUID

    # Bypass the internal-role check by overriding the dependency.
    app = create_app()

    async def _override_internal():
        return CurrentUser(
            user_id=UUID("11111111-1111-1111-1111-111111111111"),
            email="tester@example.com",
            raw_jwt="test",
        )

    app.dependency_overrides[admin._require_internal] = _override_internal

    # Patch the service's collaborators so no network/DB is touched.
    fake_wb = _FakeWB()
    fake_repo = _FakeRepo()

    monkeypatch.setattr("app.api.admin.WorldBankClient", lambda: fake_wb)
    monkeypatch.setattr("app.api.admin.service_client", lambda: object())  # any placeholder
    monkeypatch.setattr("app.api.admin.RawObservationRepository", lambda _client: fake_repo)

    return TestClient(app), fake_repo


def test_ingest_world_bank_happy_path(client):
    c, repo = client
    r = c.post(
        "/admin/ingest/world-bank",
        headers={"Authorization": f"Bearer {_token()}"},
        json={"variables": ["gdp_capita"], "year": 2021, "notes": "manual test"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rows_inserted"] == 2
    assert body["rows_skipped_null_value"] == 0
    assert body["year"] == 2021
    assert body["variables_ingested"] == ["gdp_capita"]
    assert len(repo.observations) == 2


def test_ingest_unknown_variable_returns_400(client):
    c, _ = client
    r = c.post(
        "/admin/ingest/world-bank",
        headers={"Authorization": f"Bearer {_token()}"},
        json={"variables": ["not_a_variable"], "year": 2021},
    )
    assert r.status_code == 400
    assert "not_a_variable" in r.text
```

Note: we intentionally do not re-test missing-Authorization here. The dependency override on `_require_internal` replaces the auth chain, so re-asserting 401 on this route wouldn't actually exercise the JWT gate. Auth is already covered at the dependency level by `tests/test_auth.py` from Plan 1.

- [ ] **Step 3: Run — should pass**

```bash
pytest tests/api/test_admin_ingest.py -v
```

Expected: `2 passed`.

- [ ] **Step 4: Run the full suite — no regressions**

```bash
pytest -v
```

Expected: 23 passed, 4 deselected (21 prior + 2 new).

- [ ] **Step 5: Commit + push**

```bash
cd ..
git add backend/tests/api
git commit -m "test(api): admin /ingest/world-bank route tests with dep overrides"
git push
```

---

## Task 9: Integration test against live World Bank API

**Files:**
- Create: `backend/tests/integration/test_world_bank_live.py`

- [ ] **Step 1: Create the test**

```python
# backend/tests/integration/test_world_bank_live.py
"""Live-network test against api.worldbank.org. Marked integration so it skips by default.

Enable with:
    pytest -m integration backend/tests/integration/test_world_bank_live.py
"""
from __future__ import annotations
import pytest

from app.ingestion.world_bank import WorldBankClient


@pytest.mark.integration
def test_fetch_gdp_capita_for_2021_returns_known_countries():
    client = WorldBankClient(timeout_seconds=20.0)
    result = client.fetch_indicator_for_year("NY.GDP.PCAP.CD", 2021)

    # We don't assert a specific number — the WB API restates history occasionally.
    # But these three ISO3 codes should always be in the response.
    assert "USA" in result
    assert "ZAF" in result
    assert "GBR" in result
    assert isinstance(result["USA"], float) or result["USA"] is None
```

- [ ] **Step 2: Confirm it runs when explicitly requested** (takes 5–15 seconds over the network)

```bash
cd backend
./.venv/Scripts/python.exe -m pytest tests/integration/test_world_bank_live.py -m integration -v
```

Expected: `1 passed`. If the network is unavailable, expect either a connection error or httpx timeout — in which case the test should be skipped manually (not by CI). Our CI does NOT run integration tests by default.

- [ ] **Step 3: Confirm the default test suite still excludes it**

```bash
./.venv/Scripts/python.exe -m pytest -v
```

Expected: `23 passed, N deselected` (the new live-network test joins the integration-deselected group).

- [ ] **Step 4: Commit + push**

```bash
cd ..
git add backend/tests/integration/test_world_bank_live.py
git commit -m "test(integration): live World Bank API smoke test"
git push
```

---

## Task 10: Manual smoke — real ingest against the dev Supabase project

**Not a code task — the user runs the ingestion endpoint once to populate `raw_observations`.**

- [ ] **Step 1: Boot the backend**

```bash
cd "C:/Users/APR/OneDrive - Anchor Point Risk (Pty) Ltd/Desktop/VS_CODE_REPOSITORY/country-risk-model/backend"
./.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
```

Expected: `Uvicorn running on http://127.0.0.1:8000`.

- [ ] **Step 2: Get a fresh JWT for the owner user**

The easiest way is via the frontend: `npm run dev` in `frontend/`, sign in as `owner@anchorpointrisk.local`, open browser DevTools → Application → Local Storage → copy the `sb-...-auth-token` value's `access_token` field. Alternatively, use the Supabase CLI `supabase auth login` and decode its session.

For a quick check, you can also call the Supabase REST endpoint directly:

```bash
curl -s "https://bqwnwuncwwiicgvfnuzv.supabase.co/auth/v1/token?grant_type=password" \
  -H "apikey: <ANON_KEY from your .env>" \
  -H "Content-Type: application/json" \
  -d '{"email":"owner@anchorpointrisk.local","password":"<the password you set>"}' | jq -r .access_token
```

Save the returned token as `$TOKEN`.

- [ ] **Step 3: Call the ingest endpoint**

In another terminal (keep uvicorn running):

```bash
curl -s -X POST "http://localhost:8000/admin/ingest/world-bank" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "variables": ["gdp_capita", "rol", "pr"],
    "year": 2021,
    "notes": "first live ingest"
  }' | jq
```

Expected response (approximate — exact counts depend on WB data availability):

```json
{
  "upload_id": "<uuid>",
  "source": "WB",
  "year": 2021,
  "variables_ingested": ["gdp_capita", "rol", "pr"],
  "rows_inserted": 450,
  "rows_skipped_unknown_country": 70,
  "rows_skipped_null_value": 15,
  "warnings": []
}
```

- [ ] **Step 4: Verify in Supabase Studio**

In the SQL editor for the dev project, run:

```sql
SELECT variable_code, count(*)
FROM raw_observations
WHERE year = 2021
GROUP BY variable_code
ORDER BY variable_code;

SELECT source, count(*) FROM data_uploads GROUP BY source;
```

Expected:
- ~150 rows per variable (not every country in our reference table has every indicator).
- 1 `data_uploads` row with `source = 'WB'`.

- [ ] **Step 5: Reply to the orchestrator with the results** (upload_id + row counts).

---

## Task 11: Tag and close Plan 3

- [ ] **Step 1: Final run of the default suite**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest -v
```

Expected: 23 passed, N deselected. No failures.

- [ ] **Step 2: Tag**

```bash
cd ..
git tag -a plan-3-ingestion -m "Plan 3 complete: raw_observations + World Bank API ingestion via /admin/ingest/world-bank"
git push --tags
```

- [ ] **Step 3: Verify tag appears**

Visit https://github.com/henrye1/country-risk-model/tags. The new tag should be listed.

---

## Validation Checklist (end-of-plan)

Tick these before declaring Plan 3 done:

- [ ] Migration `20260419000005_raw_observations.sql` applied; Studio shows `raw_observations` and `data_uploads` with RLS enabled.
- [ ] `backend/app/ingestion/world_bank.py` + `variable_sources.py` exist, unit-tested with respx.
- [ ] `IngestionService` orchestrates fetch → persist with proper skip accounting (null values, unknown iso3).
- [ ] `/admin/ingest/world-bank` endpoint returns `IngestResultOut` JSON and is gated to internal-org users only.
- [ ] `pytest -v` (unit suite): 23 passed, no failures.
- [ ] Live-network integration test (`pytest -m integration`) passes at least once manually.
- [ ] A real ingest call (Task 10) populated `raw_observations` with at least one year of data.
- [ ] Tag `plan-3-ingestion` pushed to GitHub.

When all ticked: ready for **Plan 4 — Snapshot lifecycle & publish** (the core audit-gated scoring workflow that makes country scores consumable by your PD/LGD models).
