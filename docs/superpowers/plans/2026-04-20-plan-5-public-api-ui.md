# Plan 5 — Public read API & Country UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the published country risk scores to authenticated users (including the PD/LGD service account) via stable `/v1/*` endpoints, and surface them in the React SPA with a country list (latest scores) and a country detail screen (headline score, driver breakdown, published history).

**Architecture:** A new `published_score` repository wraps all read paths against `score_snapshots` + `country_scores` + `driver_scores` using the user's JWT-scoped Supabase client (so RLS enforces "published only" automatically). Seven new public endpoints mirror the spec §5.1. Frontend gains one enhanced list page and one new detail page using TanStack Query for fetch/caching and Recharts for two visualisations.

**Tech Stack:** FastAPI + Pydantic (backend), React + TypeScript + Vite + TanStack Query + Recharts + Zod (frontend). No new backend dependencies; frontend adds `recharts`.

**Precondition:** Plan 4 tagged `plan-4-snapshot-lifecycle`. At least one published snapshot exists in the dev DB (confirmed: `c3fdacb1-70ef-43ac-848a-a2b8527166cd` with 60 scored countries).

---

## Design notes

### RLS leveraging
- Reads use `user_client(jwt)` so Supabase RLS automatically restricts rows to published snapshots for client users and service-reader (the PD/LGD account).
- Internal-org users can additionally see drafts, but the `/v1/*` endpoints intentionally **filter to `status='published'`** at the application layer anyway so behaviour is identical regardless of role.

### Latest-score semantics
- "Latest score for country X" = the `country_scores` row from the published snapshot with the greatest `published_at`.
- Countries not present in the latest snapshot (e.g. because data was missing at compute time) return `latest_score: null` in the list endpoint.
- Same semantics for `/score` (single-country). `?as_of=YYYY-MM-DD` returns the snapshot with greatest `published_at ≤ given date`.

### Shared schema with admin
Several Pydantic models (e.g. `SnapshotOut`) are already defined in `app/schemas/snapshot.py` (Plan 4). The public endpoints reuse them where applicable; new schemas (`CountrySummaryOut`, `DriverBreakdownOut`, etc.) live in the same file.

### Out of scope (deferred)
- What-if simulate endpoint + UI (Plan 6)
- Watchlists / alerts UI (Plan 6)
- CSV bulk export of snapshot scores (`/v1/snapshots/{id}/scores?format=csv`) — can add in a later micro-plan if needed
- PDF export
- Real-time invalidation of frontend caches on publish (hard refresh works; TanStack Query revalidates on mount/window-focus anyway)

---

## File Structure After This Plan

```
country-risk-model/
├── backend/
│   ├── app/
│   │   ├── repositories/
│   │   │   └── published_score.py        # NEW — all public read queries
│   │   ├── schemas/
│   │   │   ├── country.py                # MODIFY: add CountrySummaryOut, CountryScoreOut
│   │   │   └── snapshot.py               # MODIFY: add PublishedSnapshotOut, DriverBreakdownOut, HistoryPointOut
│   │   └── api/
│   │       └── public.py                 # MODIFY: add 7 new endpoints
│   └── tests/
│       └── api/
│           └── test_public_scores.py     # NEW (mocked repo, route-level tests)
└── frontend/
    ├── package.json                      # MODIFY: add `recharts`
    └── src/
        ├── lib/
        │   └── api.ts                    # MODIFY: typed fetchers + Zod schemas for new endpoints
        ├── routes.tsx                    # MODIFY: add `/countries/:iso3` route
        └── features/
            └── countries/
                ├── CountryListPage.tsx   # MODIFY: add latest-score column, clickable rows
                └── CountryDetailPage.tsx # NEW — headline + driver chart + history chart
```

---

## Task 1: Published-score repository

**Files:**
- Create: `backend/app/repositories/published_score.py`

No TDD here — this is pure Supabase plumbing. Tested at the route layer in Task 9.

- [ ] **Step 1: Create the file**

```python
"""Read-only access to published country scores.

All queries filter to status='published' at the application layer. RLS adds
another guard for non-internal users; both working together means a client
user cannot ever see draft data even if a bug removed a filter.
"""
from __future__ import annotations
from datetime import date
from uuid import UUID

from supabase import Client


class PublishedScoreRepository:
    def __init__(self, client: Client) -> None:
        self._client = client

    # --- Snapshots ---

    def list_published_snapshots(self, limit: int = 50) -> list[dict]:
        resp = (
            self._client.table("score_snapshots")
            .select("id, name, as_of_date, status, model_version_high, model_version_low, model_version_nodata, published_at, published_notes")
            .eq("status", "published")
            .order("published_at", desc=True)
            .limit(limit)
            .execute()
        )
        return resp.data

    def get_published_snapshot(self, snapshot_id: UUID) -> dict | None:
        resp = (
            self._client.table("score_snapshots")
            .select("*")
            .eq("id", str(snapshot_id))
            .eq("status", "published")
            .limit(1)
            .execute()
        )
        return resp.data[0] if resp.data else None

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

    def published_snapshot_as_of(self, as_of: date) -> dict | None:
        """Published snapshot with greatest published_at <= as_of."""
        resp = (
            self._client.table("score_snapshots")
            .select("*")
            .eq("status", "published")
            .lte("published_at", as_of.isoformat() + "T23:59:59Z")
            .order("published_at", desc=True)
            .limit(1)
            .execute()
        )
        return resp.data[0] if resp.data else None

    # --- Scores ---

    def scores_for_snapshot(self, snapshot_id: UUID) -> list[dict]:
        resp = (
            self._client.table("country_scores")
            .select("iso3, segment, final_score, quant_score, qual_score, bucket_band")
            .eq("snapshot_id", str(snapshot_id))
            .order("iso3")
            .execute()
        )
        return resp.data

    def score_for_country_in_snapshot(self, snapshot_id: UUID, iso3: str) -> dict | None:
        resp = (
            self._client.table("country_scores")
            .select("iso3, segment, final_score, quant_score, qual_score, bucket_band")
            .eq("snapshot_id", str(snapshot_id))
            .eq("iso3", iso3)
            .limit(1)
            .execute()
        )
        return resp.data[0] if resp.data else None

    def history_for_country(self, iso3: str) -> list[dict]:
        """Return all published snapshots that have a score for this country,
        ordered oldest-to-newest (for line chart rendering).
        """
        # Join country_scores → score_snapshots; Supabase-py supports foreign-key embedding.
        resp = (
            self._client.table("country_scores")
            .select("final_score, quant_score, qual_score, segment, bucket_band, "
                    "score_snapshots!inner(id, name, as_of_date, published_at, status)")
            .eq("iso3", iso3)
            .eq("score_snapshots.status", "published")
            .execute()
        )
        # Sort in Python (PostgREST foreign-table ordering syntax varies by client version).
        rows = resp.data
        rows.sort(key=lambda r: (r.get("score_snapshots") or {}).get("as_of_date") or "")
        return rows

    # --- Driver breakdown ---

    def drivers_for_country_in_snapshot(self, snapshot_id: UUID, iso3: str) -> list[dict]:
        """Driver scores plus variable metadata (name, category) for display."""
        resp = (
            self._client.table("driver_scores")
            .select("variable_code, raw_value, standardised_value, bucket_score, contribution, "
                    "variables!inner(name, category, direction, is_quantitative)")
            .eq("snapshot_id", str(snapshot_id))
            .eq("iso3", iso3)
            .execute()
        )
        return resp.data

    # --- Bulk latest score per country (for the countries list page) ---

    def latest_scores_map(self) -> dict[str, dict]:
        """Return {iso3: country_score row} for the single most-recently-published snapshot.

        Countries not present in that snapshot are absent from the dict. The caller
        fills `None` for those when building the response.
        """
        latest = self.latest_published_snapshot()
        if not latest:
            return {}
        rows = self.scores_for_snapshot(UUID(latest["id"]))
        by_iso3 = {r["iso3"]: r for r in rows}
        for r in by_iso3.values():
            r["snapshot_id"] = latest["id"]
            r["snapshot_name"] = latest["name"]
            r["as_of_date"] = latest["as_of_date"]
            r["published_at"] = latest["published_at"]
        return by_iso3
```

- [ ] **Step 2: Smoke-import**

```bash
cd "C:/Users/APR/OneDrive - Anchor Point Risk (Pty) Ltd/Desktop/VS_CODE_REPOSITORY/country-risk-model/backend"
./.venv/Scripts/python.exe -c "from app.repositories.published_score import PublishedScoreRepository; print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Commit + push**

```bash
cd ..
git add backend/app/repositories/published_score.py
git commit -m "feat(backend): published score repository (read-only, RLS-respecting)"
git push
```

---

## Task 2: Public API schemas

**Files:**
- Modify: `backend/app/schemas/country.py` — add CountrySummaryOut, CountryScoreOut
- Modify: `backend/app/schemas/snapshot.py` — add DriverBreakdownOut, HistoryPointOut, PublishedSnapshotOut

- [ ] **Step 1: Update `backend/app/schemas/country.py`**

Replace the entire file with:

```python
from __future__ import annotations
from datetime import date, datetime
from uuid import UUID
from pydantic import BaseModel


class CountryOut(BaseModel):
    """Basic country reference data (pre-Plan-5 shape; still used by /v1/variables consumers)."""
    iso3: str
    name: str
    region: str | None = None


class CountrySummaryOut(BaseModel):
    """Country with latest published score (nullable if none available)."""
    iso3: str
    name: str
    region: str | None = None
    latest_final_score: float | None = None
    latest_bucket_band: str | None = None
    latest_segment: str | None = None
    latest_snapshot_id: UUID | None = None
    latest_as_of_date: date | None = None
    latest_published_at: datetime | None = None


class CountryScoreOut(BaseModel):
    """One published score for one country at a point in time.

    Includes the snapshot metadata and the model version IDs used — this is the
    audit-grade shape that PD/LGD consumers log alongside their own output.
    """
    iso3: str
    name: str
    segment: str
    final_score: float
    quant_score: float
    qual_score: float
    bucket_band: str | None
    snapshot_id: UUID
    snapshot_name: str
    as_of_date: date
    published_at: datetime
    model_version_high: UUID | None
    model_version_low: UUID | None
    model_version_nodata: UUID | None
```

- [ ] **Step 2: Append to `backend/app/schemas/snapshot.py`**

Use Edit. Find the final line of the existing file (the last `rows: list[DiffRowOut]` in `DiffOut`). After that closing bracket and blank line, APPEND:

```python


class PublishedSnapshotOut(BaseModel):
    id: UUID
    name: str
    as_of_date: date
    status: str
    model_version_high: UUID | None
    model_version_low: UUID | None
    model_version_nodata: UUID | None
    published_at: datetime
    published_notes: str | None = None


class HistoryPointOut(BaseModel):
    snapshot_id: UUID
    snapshot_name: str
    as_of_date: date
    published_at: datetime
    segment: str
    final_score: float
    quant_score: float
    qual_score: float
    bucket_band: str | None


class DriverBreakdownOut(BaseModel):
    variable_code: str
    variable_name: str
    category: str
    direction: str
    is_quantitative: bool
    raw_value: float | None
    standardised_value: float | None
    bucket_score: float | None
    contribution: float
```

- [ ] **Step 3: Smoke-import**

```bash
cd backend
./.venv/Scripts/python.exe -c "from app.schemas.country import CountrySummaryOut, CountryScoreOut; from app.schemas.snapshot import PublishedSnapshotOut, HistoryPointOut, DriverBreakdownOut; print('ok')"
```

Expected: `ok`.

- [ ] **Step 4: Run existing tests — no regressions**

```bash
./.venv/Scripts/python.exe -m pytest -v
```

Expected: 37 passed, 5 deselected.

- [ ] **Step 5: Commit + push**

```bash
cd ..
git add backend/app/schemas/country.py backend/app/schemas/snapshot.py
git commit -m "feat(schemas): public-read schemas for scores, history, drivers, snapshots"
git push
```

---

## Task 3: Update /v1/countries to include latest score

**Files:**
- Modify: `backend/app/api/public.py`

Current `/v1/countries` returns a plain list of `CountryOut`. We enhance it to return `CountrySummaryOut` with the latest-published-score fields populated.

- [ ] **Step 1: Edit `backend/app/api/public.py`**

Use Edit. Find:

```python
@router.get("/countries", response_model=list[CountryOut])
def list_countries(user: CurrentUser = Depends(get_current_user)) -> list[CountryOut]:
    repo = ReferenceRepository(user_client(user.raw_jwt))
    return repo.list_countries()
```

Replace with:

```python
@router.get("/countries", response_model=list[CountrySummaryOut])
def list_countries(user: CurrentUser = Depends(get_current_user)) -> list[CountrySummaryOut]:
    ref_repo = ReferenceRepository(user_client(user.raw_jwt))
    pub_repo = PublishedScoreRepository(user_client(user.raw_jwt))

    countries = ref_repo.list_countries()
    latest = pub_repo.latest_scores_map()

    out: list[CountrySummaryOut] = []
    for c in countries:
        score = latest.get(c.iso3)
        out.append(CountrySummaryOut(
            iso3=c.iso3,
            name=c.name,
            region=c.region,
            latest_final_score=float(score["final_score"]) if score else None,
            latest_bucket_band=score["bucket_band"] if score else None,
            latest_segment=score["segment"] if score else None,
            latest_snapshot_id=score["snapshot_id"] if score else None,
            latest_as_of_date=score["as_of_date"] if score else None,
            latest_published_at=score["published_at"] if score else None,
        ))
    return out
```

And update the imports at the top of the file. Find:

```python
from app.core.auth import get_current_user
from app.core.supabase import user_client
from app.repositories.reference import ReferenceRepository
from app.schemas.country import CountryOut
from app.schemas.user import CurrentUser
from app.schemas.variable import VariableOut
```

Replace with:

```python
from app.core.auth import get_current_user
from app.core.supabase import user_client
from app.repositories.published_score import PublishedScoreRepository
from app.repositories.reference import ReferenceRepository
from app.schemas.country import CountryOut, CountrySummaryOut
from app.schemas.user import CurrentUser
from app.schemas.variable import VariableOut
```

- [ ] **Step 2: Verify the test suite still passes**

Note: the existing integration test (`tests/test_public_countries.py`) asserts `len(r.json()) >= 150` but doesn't check the shape — so it should still pass because the response is still a list of 150+ items. Confirm:

```bash
cd backend
./.venv/Scripts/python.exe -m pytest -v
```

Expected: 37 passed.

- [ ] **Step 3: Commit + push**

```bash
cd ..
git add backend/app/api/public.py
git commit -m "feat(api): /v1/countries — return latest published score per country"
git push
```

---

## Task 4: Country detail + score endpoints

**Files:**
- Modify: `backend/app/api/public.py`

Four new endpoints:
- `GET /v1/countries/{iso3}` → single CountrySummaryOut
- `GET /v1/countries/{iso3}/score` → CountryScoreOut (latest, or by ?as_of=, or by ?snapshot_id=)
- `GET /v1/countries/{iso3}/score/drivers?snapshot_id=UUID` → list[DriverBreakdownOut]
- `GET /v1/countries/{iso3}/history` → list[HistoryPointOut] (ascending date)

- [ ] **Step 1: Edit `backend/app/api/public.py`**

Update imports to add:

```python
from datetime import date as _date
from uuid import UUID
from fastapi import HTTPException, Query, status as _status
from app.schemas.snapshot import DriverBreakdownOut, HistoryPointOut
```

Append these handlers at the end of the file:

```python


@router.get("/countries/{iso3}", response_model=CountrySummaryOut)
def get_country(
    iso3: str,
    user: CurrentUser = Depends(get_current_user),
) -> CountrySummaryOut:
    ref_repo = ReferenceRepository(user_client(user.raw_jwt))
    pub_repo = PublishedScoreRepository(user_client(user.raw_jwt))

    countries = {c.iso3: c for c in ref_repo.list_countries()}
    c = countries.get(iso3.upper())
    if not c:
        raise HTTPException(status_code=_status.HTTP_404_NOT_FOUND, detail=f"country '{iso3}' not found")

    latest = pub_repo.latest_scores_map().get(c.iso3)
    return CountrySummaryOut(
        iso3=c.iso3,
        name=c.name,
        region=c.region,
        latest_final_score=float(latest["final_score"]) if latest else None,
        latest_bucket_band=latest["bucket_band"] if latest else None,
        latest_segment=latest["segment"] if latest else None,
        latest_snapshot_id=latest["snapshot_id"] if latest else None,
        latest_as_of_date=latest["as_of_date"] if latest else None,
        latest_published_at=latest["published_at"] if latest else None,
    )


@router.get("/countries/{iso3}/score", response_model=CountryScoreOut)
def get_country_score(
    iso3: str,
    as_of: _date | None = Query(default=None),
    snapshot_id: UUID | None = Query(default=None),
    user: CurrentUser = Depends(get_current_user),
) -> CountryScoreOut:
    if as_of is not None and snapshot_id is not None:
        raise HTTPException(status_code=_status.HTTP_400_BAD_REQUEST, detail="pass at most one of ?as_of and ?snapshot_id")

    ref_repo = ReferenceRepository(user_client(user.raw_jwt))
    pub_repo = PublishedScoreRepository(user_client(user.raw_jwt))

    countries = {c.iso3: c for c in ref_repo.list_countries()}
    c = countries.get(iso3.upper())
    if not c:
        raise HTTPException(status_code=_status.HTTP_404_NOT_FOUND, detail=f"country '{iso3}' not found")

    # Resolve which snapshot we're reading from.
    if snapshot_id is not None:
        snap = pub_repo.get_published_snapshot(snapshot_id)
    elif as_of is not None:
        snap = pub_repo.published_snapshot_as_of(as_of)
    else:
        snap = pub_repo.latest_published_snapshot()

    if snap is None:
        raise HTTPException(status_code=_status.HTTP_404_NOT_FOUND, detail="no published snapshot matches the query")

    score = pub_repo.score_for_country_in_snapshot(UUID(snap["id"]), c.iso3)
    if score is None:
        raise HTTPException(status_code=_status.HTTP_404_NOT_FOUND, detail=f"country '{iso3}' not scored in snapshot '{snap['id']}'")

    return CountryScoreOut(
        iso3=c.iso3,
        name=c.name,
        segment=score["segment"],
        final_score=float(score["final_score"]),
        quant_score=float(score["quant_score"]),
        qual_score=float(score["qual_score"]),
        bucket_band=score["bucket_band"],
        snapshot_id=UUID(snap["id"]),
        snapshot_name=snap["name"],
        as_of_date=snap["as_of_date"],
        published_at=snap["published_at"],
        model_version_high=UUID(snap["model_version_high"]) if snap.get("model_version_high") else None,
        model_version_low=UUID(snap["model_version_low"]) if snap.get("model_version_low") else None,
        model_version_nodata=UUID(snap["model_version_nodata"]) if snap.get("model_version_nodata") else None,
    )


@router.get("/countries/{iso3}/score/drivers", response_model=list[DriverBreakdownOut])
def get_country_drivers(
    iso3: str,
    snapshot_id: UUID,
    user: CurrentUser = Depends(get_current_user),
) -> list[DriverBreakdownOut]:
    pub_repo = PublishedScoreRepository(user_client(user.raw_jwt))

    # Verify the snapshot is published — prevents leaking draft drivers via this route.
    snap = pub_repo.get_published_snapshot(snapshot_id)
    if snap is None:
        raise HTTPException(status_code=_status.HTTP_404_NOT_FOUND, detail="snapshot not found or not published")

    rows = pub_repo.drivers_for_country_in_snapshot(snapshot_id, iso3.upper())
    out: list[DriverBreakdownOut] = []
    for r in rows:
        variable = r.get("variables") or {}
        out.append(DriverBreakdownOut(
            variable_code=r["variable_code"],
            variable_name=variable.get("name", r["variable_code"]),
            category=variable.get("category", ""),
            direction=variable.get("direction", ""),
            is_quantitative=variable.get("is_quantitative", False),
            raw_value=float(r["raw_value"]) if r.get("raw_value") is not None else None,
            standardised_value=float(r["standardised_value"]) if r.get("standardised_value") is not None else None,
            bucket_score=float(r["bucket_score"]) if r.get("bucket_score") is not None else None,
            contribution=float(r["contribution"]),
        ))
    return out


@router.get("/countries/{iso3}/history", response_model=list[HistoryPointOut])
def get_country_history(
    iso3: str,
    user: CurrentUser = Depends(get_current_user),
) -> list[HistoryPointOut]:
    pub_repo = PublishedScoreRepository(user_client(user.raw_jwt))
    rows = pub_repo.history_for_country(iso3.upper())

    out: list[HistoryPointOut] = []
    for r in rows:
        snap = r.get("score_snapshots") or {}
        out.append(HistoryPointOut(
            snapshot_id=UUID(snap["id"]),
            snapshot_name=snap["name"],
            as_of_date=snap["as_of_date"],
            published_at=snap["published_at"],
            segment=r["segment"],
            final_score=float(r["final_score"]),
            quant_score=float(r["quant_score"]),
            qual_score=float(r["qual_score"]),
            bucket_band=r.get("bucket_band"),
        ))
    return out
```

- [ ] **Step 2: Smoke-check routes**

```bash
cd backend
./.venv/Scripts/python.exe -c "from app.main import create_app; app = create_app(); print(sorted([r.path for r in app.routes if hasattr(r, 'path') and r.path.startswith('/v1/countries')]))"
```

Expected: 5 paths including `/v1/countries`, `/v1/countries/{iso3}`, `/v1/countries/{iso3}/score`, `/v1/countries/{iso3}/score/drivers`, `/v1/countries/{iso3}/history`.

- [ ] **Step 3: Full test suite — no regressions**

```bash
./.venv/Scripts/python.exe -m pytest -v
```

Expected: 37 passed, 5 deselected.

- [ ] **Step 4: Commit + push**

```bash
cd ..
git add backend/app/api/public.py
git commit -m "feat(api): /v1/countries/{iso3} detail + score + drivers + history"
git push
```

---

## Task 5: Snapshot read endpoints

**Files:**
- Modify: `backend/app/api/public.py`

Three endpoints:
- `GET /v1/snapshots` → list of published snapshots
- `GET /v1/snapshots/{id}` → detail of a single published snapshot
- `GET /v1/snapshots/{id}/scores` → all country scores in a snapshot

- [ ] **Step 1: Update imports in `backend/app/api/public.py`**

Add:

```python
from app.schemas.snapshot import PublishedSnapshotOut
```

- [ ] **Step 2: Append the three endpoints**

```python


@router.get("/snapshots", response_model=list[PublishedSnapshotOut])
def list_published_snapshots(
    user: CurrentUser = Depends(get_current_user),
) -> list[PublishedSnapshotOut]:
    pub_repo = PublishedScoreRepository(user_client(user.raw_jwt))
    rows = pub_repo.list_published_snapshots(limit=100)
    return [PublishedSnapshotOut(**r) for r in rows]


@router.get("/snapshots/{snapshot_id}", response_model=PublishedSnapshotOut)
def get_published_snapshot_detail(
    snapshot_id: UUID,
    user: CurrentUser = Depends(get_current_user),
) -> PublishedSnapshotOut:
    pub_repo = PublishedScoreRepository(user_client(user.raw_jwt))
    snap = pub_repo.get_published_snapshot(snapshot_id)
    if snap is None:
        raise HTTPException(status_code=_status.HTTP_404_NOT_FOUND, detail="snapshot not found or not published")
    return PublishedSnapshotOut(**snap)


@router.get("/snapshots/{snapshot_id}/scores", response_model=list[CountryScoreOut])
def get_snapshot_scores(
    snapshot_id: UUID,
    user: CurrentUser = Depends(get_current_user),
) -> list[CountryScoreOut]:
    ref_repo = ReferenceRepository(user_client(user.raw_jwt))
    pub_repo = PublishedScoreRepository(user_client(user.raw_jwt))

    snap = pub_repo.get_published_snapshot(snapshot_id)
    if snap is None:
        raise HTTPException(status_code=_status.HTTP_404_NOT_FOUND, detail="snapshot not found or not published")

    countries = {c.iso3: c for c in ref_repo.list_countries()}
    rows = pub_repo.scores_for_snapshot(snapshot_id)

    out: list[CountryScoreOut] = []
    for r in rows:
        c = countries.get(r["iso3"])
        if c is None:
            continue  # orphaned score row; skip
        out.append(CountryScoreOut(
            iso3=c.iso3,
            name=c.name,
            segment=r["segment"],
            final_score=float(r["final_score"]),
            quant_score=float(r["quant_score"]),
            qual_score=float(r["qual_score"]),
            bucket_band=r.get("bucket_band"),
            snapshot_id=UUID(snap["id"]),
            snapshot_name=snap["name"],
            as_of_date=snap["as_of_date"],
            published_at=snap["published_at"],
            model_version_high=UUID(snap["model_version_high"]) if snap.get("model_version_high") else None,
            model_version_low=UUID(snap["model_version_low"]) if snap.get("model_version_low") else None,
            model_version_nodata=UUID(snap["model_version_nodata"]) if snap.get("model_version_nodata") else None,
        ))
    return out
```

- [ ] **Step 3: Smoke + tests**

```bash
cd backend
./.venv/Scripts/python.exe -c "from app.main import create_app; app = create_app(); print(sorted([r.path for r in app.routes if hasattr(r, 'path') and r.path.startswith('/v1/snapshot')]))"
./.venv/Scripts/python.exe -m pytest -v
```

Expected: 3 `/v1/snapshot*` paths listed; 37 pytest passes.

- [ ] **Step 4: Commit + push**

```bash
cd ..
git add backend/app/api/public.py
git commit -m "feat(api): /v1/snapshots list + detail + scores endpoints"
git push
```

---

## Task 6: Route-level tests for new public endpoints

**Files:**
- Create: `backend/tests/api/test_public_scores.py`

Tests use a stub repository injected via dependency override — no real Supabase calls.

- [ ] **Step 1: Write the tests**

```python
from __future__ import annotations
import time
from uuid import UUID
import pytest
from jose import jwt
from fastapi.testclient import TestClient

JWT_SECRET = "test-jwt-secret"
SID = UUID("11111111-1111-1111-1111-111111111111")


def _token(user_id: str = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa") -> str:
    payload = {
        "sub": user_id,
        "email": "tester@example.com",
        "aud": "authenticated",
        "role": "authenticated",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


class _FakeRefRepo:
    def list_countries(self):
        from app.schemas.country import CountryOut
        return [
            CountryOut(iso3="USA", name="UNITED STATES", region="DEVELOPED"),
            CountryOut(iso3="ZAF", name="SOUTH AFRICA", region="AFRICA"),
        ]

    def list_variables(self):
        return []


class _FakePubRepo:
    def __init__(self) -> None:
        self.snap = {
            "id": str(SID),
            "name": "2022-FY-subset",
            "as_of_date": "2022-12-31",
            "status": "published",
            "model_version_high": None,
            "model_version_low": None,
            "model_version_nodata": None,
            "published_at": "2026-04-20T10:00:00Z",
            "published_notes": "first",
        }

    def latest_published_snapshot(self):
        return self.snap

    def get_published_snapshot(self, _id):
        return self.snap if str(_id) == self.snap["id"] else None

    def published_snapshot_as_of(self, _date):
        return self.snap

    def list_published_snapshots(self, limit=50):
        return [self.snap]

    def latest_scores_map(self):
        return {
            "USA": {
                "iso3": "USA", "segment": "HIGH", "final_score": 1.5,
                "quant_score": 1.0, "qual_score": 0.5, "bucket_band": None,
                "snapshot_id": self.snap["id"], "snapshot_name": self.snap["name"],
                "as_of_date": self.snap["as_of_date"], "published_at": self.snap["published_at"],
            }
        }

    def scores_for_snapshot(self, _id):
        return [
            {"iso3": "USA", "segment": "HIGH", "final_score": 1.5,
             "quant_score": 1.0, "qual_score": 0.5, "bucket_band": None},
        ]

    def score_for_country_in_snapshot(self, _id, iso3):
        if iso3 != "USA":
            return None
        return self.scores_for_snapshot(_id)[0]

    def history_for_country(self, _iso3):
        return [
            {
                "final_score": 1.2, "quant_score": 1.0, "qual_score": 0.2,
                "segment": "HIGH", "bucket_band": None,
                "score_snapshots": self.snap,
            },
        ]

    def drivers_for_country_in_snapshot(self, _id, _iso3):
        return [
            {
                "variable_code": "gdp_capita",
                "raw_value": 70000.0, "standardised_value": 1.0,
                "bucket_score": 1.0, "contribution": 1.0,
                "variables": {"name": "GDP per capita", "category": "Economic",
                              "direction": "higher_better", "is_quantitative": True},
            },
        ]


@pytest.fixture
def client(monkeypatch):
    from app.main import create_app
    app = create_app()
    monkeypatch.setattr("app.api.public.ReferenceRepository", lambda _client: _FakeRefRepo())
    monkeypatch.setattr("app.api.public.PublishedScoreRepository", lambda _client: _FakePubRepo())
    monkeypatch.setattr("app.api.public.user_client", lambda _jwt: object())
    return TestClient(app)


def test_list_countries_includes_latest_score(client):
    r = client.get("/v1/countries", headers={"Authorization": f"Bearer {_token()}"})
    assert r.status_code == 200, r.text
    body = r.json()
    usa = next(b for b in body if b["iso3"] == "USA")
    zaf = next(b for b in body if b["iso3"] == "ZAF")
    assert usa["latest_final_score"] == 1.5
    assert zaf["latest_final_score"] is None  # not in the latest_scores_map


def test_country_detail_returns_latest_score(client):
    r = client.get("/v1/countries/USA", headers={"Authorization": f"Bearer {_token()}"})
    assert r.status_code == 200
    body = r.json()
    assert body["iso3"] == "USA"
    assert body["latest_final_score"] == 1.5


def test_country_detail_404_for_unknown(client):
    r = client.get("/v1/countries/QQQ", headers={"Authorization": f"Bearer {_token()}"})
    assert r.status_code == 404


def test_country_score_default_returns_latest(client):
    r = client.get("/v1/countries/USA/score", headers={"Authorization": f"Bearer {_token()}"})
    assert r.status_code == 200
    body = r.json()
    assert body["final_score"] == 1.5
    assert body["snapshot_id"] == str(SID)


def test_country_score_rejects_both_query_params(client):
    r = client.get(
        "/v1/countries/USA/score?as_of=2022-12-31&snapshot_id=" + str(SID),
        headers={"Authorization": f"Bearer {_token()}"},
    )
    assert r.status_code == 400


def test_country_history_returns_list(client):
    r = client.get("/v1/countries/USA/history", headers={"Authorization": f"Bearer {_token()}"})
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["segment"] == "HIGH"


def test_country_drivers_requires_snapshot_id(client):
    r = client.get("/v1/countries/USA/score/drivers", headers={"Authorization": f"Bearer {_token()}"})
    assert r.status_code == 422  # FastAPI validation error for missing query param


def test_country_drivers_with_snapshot_id(client):
    r = client.get(
        f"/v1/countries/USA/score/drivers?snapshot_id={SID}",
        headers={"Authorization": f"Bearer {_token()}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body[0]["variable_code"] == "gdp_capita"
    assert body[0]["variable_name"] == "GDP per capita"


def test_list_snapshots_returns_published_only(client):
    r = client.get("/v1/snapshots", headers={"Authorization": f"Bearer {_token()}"})
    assert r.status_code == 200
    assert r.json()[0]["status"] == "published"


def test_snapshot_scores_returns_country_scores(client):
    r = client.get(f"/v1/snapshots/{SID}/scores", headers={"Authorization": f"Bearer {_token()}"})
    assert r.status_code == 200
    body = r.json()
    assert body[0]["iso3"] == "USA"
    assert body[0]["snapshot_id"] == str(SID)
```

- [ ] **Step 2: Run**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest tests/api/test_public_scores.py -v
```

Expected: `10 passed`.

- [ ] **Step 3: Full suite**

```bash
./.venv/Scripts/python.exe -m pytest -v
```

Expected: 47 passed, 5 deselected (37 prior + 10 new).

- [ ] **Step 4: Commit + push**

```bash
cd ..
git add backend/tests/api/test_public_scores.py
git commit -m "test(api): route-level tests for all new public score endpoints"
git push
```

---

## Task 7: Frontend — add Recharts + update API client

**Files:**
- Modify: `frontend/package.json` — add recharts
- Modify: `frontend/src/lib/api.ts` — add typed fetchers + Zod schemas for new endpoints

- [ ] **Step 1: Install Recharts**

```bash
cd "C:/Users/APR/OneDrive - Anchor Point Risk (Pty) Ltd/Desktop/VS_CODE_REPOSITORY/country-risk-model/frontend"
npm i recharts
```

Expected: package added.

- [ ] **Step 2: Replace `frontend/src/lib/api.ts`**

```ts
import { z } from "zod";
import { supabase } from "./supabase";

const API_BASE = import.meta.env.VITE_API_BASE_URL;

export class ApiError extends Error {
  public status: number;
  public details?: unknown;
  constructor(status: number, message: string, details?: unknown) {
    super(message);
    this.status = status;
    this.details = details;
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

// --- Shared primitives ---------------------------------------------------

export const IsoDate = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);

// --- Reference types -----------------------------------------------------

export const Variable = z.object({
  code: z.string(),
  name: z.string(),
  category: z.string(),
  direction: z.string(),
  is_quantitative: z.boolean(),
  description: z.string().nullable().optional(),
});
export type Variable = z.infer<typeof Variable>;

// --- Country types -------------------------------------------------------

export const CountrySummary = z.object({
  iso3: z.string().length(3),
  name: z.string(),
  region: z.string().nullable().optional(),
  latest_final_score: z.number().nullable(),
  latest_bucket_band: z.string().nullable(),
  latest_segment: z.string().nullable(),
  latest_snapshot_id: z.string().uuid().nullable(),
  latest_as_of_date: IsoDate.nullable(),
  latest_published_at: z.string().nullable(),
});
export type CountrySummary = z.infer<typeof CountrySummary>;

export const CountryScore = z.object({
  iso3: z.string().length(3),
  name: z.string(),
  segment: z.string(),
  final_score: z.number(),
  quant_score: z.number(),
  qual_score: z.number(),
  bucket_band: z.string().nullable(),
  snapshot_id: z.string().uuid(),
  snapshot_name: z.string(),
  as_of_date: IsoDate,
  published_at: z.string(),
  model_version_high: z.string().uuid().nullable(),
  model_version_low: z.string().uuid().nullable(),
  model_version_nodata: z.string().uuid().nullable(),
});
export type CountryScore = z.infer<typeof CountryScore>;

export const DriverBreakdown = z.object({
  variable_code: z.string(),
  variable_name: z.string(),
  category: z.string(),
  direction: z.string(),
  is_quantitative: z.boolean(),
  raw_value: z.number().nullable(),
  standardised_value: z.number().nullable(),
  bucket_score: z.number().nullable(),
  contribution: z.number(),
});
export type DriverBreakdown = z.infer<typeof DriverBreakdown>;

export const HistoryPoint = z.object({
  snapshot_id: z.string().uuid(),
  snapshot_name: z.string(),
  as_of_date: IsoDate,
  published_at: z.string(),
  segment: z.string(),
  final_score: z.number(),
  quant_score: z.number(),
  qual_score: z.number(),
  bucket_band: z.string().nullable(),
});
export type HistoryPoint = z.infer<typeof HistoryPoint>;

export const PublishedSnapshot = z.object({
  id: z.string().uuid(),
  name: z.string(),
  as_of_date: IsoDate,
  status: z.string(),
  model_version_high: z.string().uuid().nullable(),
  model_version_low: z.string().uuid().nullable(),
  model_version_nodata: z.string().uuid().nullable(),
  published_at: z.string(),
  published_notes: z.string().nullable().optional(),
});
export type PublishedSnapshot = z.infer<typeof PublishedSnapshot>;

// --- API surface ---------------------------------------------------------

export const api = {
  listCountries: () => request("/v1/countries", z.array(CountrySummary)),
  listVariables: () => request("/v1/variables", z.array(Variable)),
  getCountry: (iso3: string) =>
    request(`/v1/countries/${iso3}`, CountrySummary),
  getCountryScore: (iso3: string, opts?: { as_of?: string; snapshot_id?: string }) => {
    const qs = new URLSearchParams();
    if (opts?.as_of) qs.set("as_of", opts.as_of);
    if (opts?.snapshot_id) qs.set("snapshot_id", opts.snapshot_id);
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return request(`/v1/countries/${iso3}/score${suffix}`, CountryScore);
  },
  getCountryDrivers: (iso3: string, snapshot_id: string) =>
    request(
      `/v1/countries/${iso3}/score/drivers?snapshot_id=${snapshot_id}`,
      z.array(DriverBreakdown),
    ),
  getCountryHistory: (iso3: string) =>
    request(`/v1/countries/${iso3}/history`, z.array(HistoryPoint)),
  listSnapshots: () => request("/v1/snapshots", z.array(PublishedSnapshot)),
};

// Re-export the old Country shape for any legacy consumer (in case a test references it).
export const Country = z.object({
  iso3: z.string().length(3),
  name: z.string(),
  region: z.string().nullable().optional(),
});
export type Country = z.infer<typeof Country>;
```

- [ ] **Step 3: Typecheck**

```bash
cd frontend
npx tsc --noEmit -p tsconfig.app.json
```

Expected: no errors.

- [ ] **Step 4: Run frontend tests — no regressions**

```bash
npm test
```

Expected: all previous tests pass (3 from Plan 1).

- [ ] **Step 5: Commit + push**

```bash
cd ..
git add frontend/package.json frontend/package-lock.json frontend/src/lib/api.ts
git commit -m "feat(frontend): typed API client + Zod schemas for score endpoints; add recharts"
git push
```

---

## Task 8: Frontend — enhanced CountryListPage with score column

**Files:**
- Modify: `frontend/src/features/countries/CountryListPage.tsx`

- [ ] **Step 1: Replace the file**

```tsx
import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, type CountrySummary } from "../../lib/api";

type SortKey = "name" | "score";

export function CountryListPage() {
  const { data, isLoading, error } = useQuery({ queryKey: ["countries"], queryFn: api.listCountries });
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [query, setQuery] = useState("");

  if (isLoading) return <p className="text-sm text-slate-500">Loading countries...</p>;
  if (error) return <p role="alert" className="text-sm text-red-600">{(error as Error).message}</p>;

  const countries = data ?? [];
  const filtered = countries.filter((c) =>
    !query.trim() || c.name.toLowerCase().includes(query.toLowerCase()) || c.iso3.toLowerCase().includes(query.toLowerCase())
  );
  const sorted = [...filtered].sort((a, b) => {
    if (sortKey === "name") return a.name.localeCompare(b.name);
    // score: nulls last; higher scores first
    const av = a.latest_final_score;
    const bv = b.latest_final_score;
    if (av === null && bv === null) return a.name.localeCompare(b.name);
    if (av === null) return 1;
    if (bv === null) return -1;
    return bv - av;
  });

  const scoredCount = countries.filter((c) => c.latest_final_score !== null).length;

  return (
    <section>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-lg font-semibold text-slate-900">
          Countries <span className="text-sm font-normal text-slate-500">({scoredCount} scored / {countries.length} total)</span>
        </h1>
        <div className="flex items-center gap-3">
          <input
            type="search"
            placeholder="Filter by name or ISO3"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1 text-sm"
          />
          <label className="text-xs text-slate-600">
            Sort:&nbsp;
            <select
              value={sortKey}
              onChange={(e) => setSortKey(e.target.value as SortKey)}
              className="rounded border border-slate-300 px-2 py-0.5 text-xs"
            >
              <option value="name">Name</option>
              <option value="score">Latest score</option>
            </select>
          </label>
        </div>
      </div>
      <ul className="divide-y divide-slate-200 rounded border border-slate-200 bg-white">
        {sorted.map((c: CountrySummary) => (
          <li key={c.iso3} className="flex items-center justify-between px-4 py-2 text-sm hover:bg-slate-50">
            <Link to={`/countries/${c.iso3}`} className="flex-1 text-slate-900 hover:underline">
              {c.name}
            </Link>
            <span className="mr-4 text-xs text-slate-500">{c.iso3}</span>
            <span className="w-32 text-right font-mono text-sm text-slate-800">
              {c.latest_final_score !== null ? c.latest_final_score.toFixed(3) : <span className="text-slate-300">—</span>}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
```

- [ ] **Step 2: Update the existing test `frontend/tests/CountryListPage.test.tsx`** to match the new shape.

Read the current test first (so the Edit below has the right anchor), then replace:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { CountryListPage } from "../src/features/countries/CountryListPage";

vi.mock("../src/lib/api", () => ({
  api: {
    listCountries: vi.fn().mockResolvedValue([
      {
        iso3: "USA", name: "UNITED STATES", region: "DEVELOPED",
        latest_final_score: 1.5, latest_bucket_band: null, latest_segment: "HIGH",
        latest_snapshot_id: "11111111-1111-1111-1111-111111111111",
        latest_as_of_date: "2022-12-31", latest_published_at: "2026-04-20T10:00:00Z",
      },
      {
        iso3: "ZAF", name: "SOUTH AFRICA", region: "AFRICA",
        latest_final_score: null, latest_bucket_band: null, latest_segment: null,
        latest_snapshot_id: null, latest_as_of_date: null, latest_published_at: null,
      },
    ]),
  },
}));

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>;
}

describe("CountryListPage", () => {
  it("renders the counts and both countries", async () => {
    render(wrap(<CountryListPage />));
    await waitFor(() => expect(screen.getByText(/1 scored \/ 2 total/i)).toBeInTheDocument());
    expect(screen.getByText(/united states/i)).toBeInTheDocument();
    expect(screen.getByText(/south africa/i)).toBeInTheDocument();
  });

  it("shows the score for scored countries and a dash for unscored", async () => {
    render(wrap(<CountryListPage />));
    await waitFor(() => expect(screen.getByText("1.500")).toBeInTheDocument());
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });
});
```

- [ ] **Step 3: Run tests**

```bash
cd frontend
npm test
```

Expected: the new 2 CountryListPage tests pass + the existing LoginPage tests pass. Total: 4 passed.

- [ ] **Step 4: Commit + push**

```bash
cd ..
git add frontend/src/features/countries/CountryListPage.tsx frontend/tests/CountryListPage.test.tsx
git commit -m "feat(frontend): CountryListPage — filter/sort + latest score column + clickable rows"
git push
```

---

## Task 9: Frontend — Country detail page + route

**Files:**
- Create: `frontend/src/features/countries/CountryDetailPage.tsx`
- Modify: `frontend/src/routes.tsx` — add `/countries/:iso3` route

- [ ] **Step 1: Create `frontend/src/features/countries/CountryDetailPage.tsx`**

```tsx
import { useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, type DriverBreakdown, type HistoryPoint } from "../../lib/api";

export function CountryDetailPage() {
  const { iso3 = "" } = useParams<{ iso3: string }>();

  const summary = useQuery({
    queryKey: ["country", iso3],
    queryFn: () => api.getCountry(iso3),
    enabled: !!iso3,
  });

  const score = useQuery({
    queryKey: ["country-score", iso3],
    queryFn: () => api.getCountryScore(iso3),
    enabled: !!iso3,
    retry: false,
  });

  const drivers = useQuery({
    queryKey: ["country-drivers", iso3, score.data?.snapshot_id],
    queryFn: () => api.getCountryDrivers(iso3, score.data!.snapshot_id),
    enabled: !!score.data?.snapshot_id,
  });

  const history = useQuery({
    queryKey: ["country-history", iso3],
    queryFn: () => api.getCountryHistory(iso3),
    enabled: !!iso3,
  });

  if (summary.isLoading) return <p className="text-sm text-slate-500">Loading country...</p>;
  if (summary.error) return <p role="alert" className="text-sm text-red-600">{(summary.error as Error).message}</p>;
  if (!summary.data) return null;

  const c = summary.data;
  const scoreData = score.data;
  const noScore = score.isError || !scoreData;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3 text-sm text-slate-500">
        <Link to="/countries" className="hover:underline">← Countries</Link>
      </div>

      <header className="rounded-lg border border-slate-200 bg-white p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold text-slate-900">{c.name}</h1>
            <p className="mt-1 text-sm text-slate-500">
              {c.iso3} · {c.region ?? "—"}
              {scoreData && <> · Segment: <span className="font-mono">{scoreData.segment}</span></>}
            </p>
          </div>
          <div className="text-right">
            {noScore ? (
              <p className="text-sm text-slate-400">No published score</p>
            ) : (
              <>
                <p className="font-mono text-3xl font-semibold text-slate-900">
                  {scoreData!.final_score.toFixed(3)}
                </p>
                <p className="mt-1 text-xs text-slate-500">
                  Snapshot: {scoreData!.snapshot_name} · as of {scoreData!.as_of_date}
                </p>
                <p className="text-xs text-slate-400">
                  Published {new Date(scoreData!.published_at).toLocaleDateString()}
                </p>
              </>
            )}
          </div>
        </div>
        {!noScore && (
          <div className="mt-4 flex gap-6 text-sm">
            <Metric label="Quant" value={scoreData!.quant_score.toFixed(3)} />
            <Metric label="Qual" value={scoreData!.qual_score.toFixed(3)} />
            {scoreData!.bucket_band && <Metric label="Band" value={scoreData!.bucket_band} />}
          </div>
        )}
      </header>

      <section className="rounded-lg border border-slate-200 bg-white p-6">
        <h2 className="mb-4 text-lg font-semibold text-slate-900">Driver breakdown</h2>
        {drivers.isLoading && <p className="text-sm text-slate-500">Loading drivers...</p>}
        {drivers.error && <p role="alert" className="text-sm text-red-600">{(drivers.error as Error).message}</p>}
        {drivers.data && <DriverChart drivers={drivers.data} />}
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-6">
        <h2 className="mb-4 text-lg font-semibold text-slate-900">Score history</h2>
        {history.isLoading && <p className="text-sm text-slate-500">Loading history...</p>}
        {history.error && <p role="alert" className="text-sm text-red-600">{(history.error as Error).message}</p>}
        {history.data && history.data.length === 0 && (
          <p className="text-sm text-slate-500">No published history yet for this country.</p>
        )}
        {history.data && history.data.length > 0 && <HistoryChart history={history.data} />}
      </section>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className="font-mono text-sm text-slate-900">{value}</p>
    </div>
  );
}

function DriverChart({ drivers }: { drivers: DriverBreakdown[] }) {
  const data = useMemo(
    () => drivers
      .slice()
      .sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution))
      .map((d) => ({
        name: d.variable_name,
        contribution: d.contribution,
        category: d.category,
      })),
    [drivers],
  );
  return (
    <div className="h-80 w-full">
      <ResponsiveContainer>
        <BarChart data={data} layout="vertical" margin={{ top: 5, right: 20, left: 120, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis type="number" />
          <YAxis type="category" dataKey="name" width={120} style={{ fontSize: "12px" }} />
          <Tooltip formatter={(v: number) => v.toFixed(3)} />
          <Bar dataKey="contribution" fill="#475569" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function HistoryChart({ history }: { history: HistoryPoint[] }) {
  const data = history.map((h) => ({
    date: h.as_of_date,
    final: h.final_score,
    quant: h.quant_score,
    qual: h.qual_score,
  }));
  return (
    <div className="h-80 w-full">
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="date" style={{ fontSize: "12px" }} />
          <YAxis style={{ fontSize: "12px" }} />
          <Tooltip formatter={(v: number) => v.toFixed(3)} />
          <Line type="monotone" dataKey="final" stroke="#0f172a" strokeWidth={2} dot />
          <Line type="monotone" dataKey="quant" stroke="#64748b" strokeWidth={1} dot={false} />
          <Line type="monotone" dataKey="qual" stroke="#94a3b8" strokeWidth={1} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
```

- [ ] **Step 2: Register the route in `frontend/src/routes.tsx`**

Use Edit. Find the existing route array, specifically the entry for `/countries`:

```tsx
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
```

Replace with:

```tsx
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
  {
    path: "/countries/:iso3",
    element: (
      <RequireAuth>
        <AppShell>
          <CountryDetailPage />
        </AppShell>
      </RequireAuth>
    ),
  },
```

Also update the imports at the top of `routes.tsx`. Find:

```tsx
import { CountryListPage } from "./features/countries/CountryListPage";
```

Replace with:

```tsx
import { CountryDetailPage } from "./features/countries/CountryDetailPage";
import { CountryListPage } from "./features/countries/CountryListPage";
```

- [ ] **Step 3: Typecheck + build**

```bash
cd frontend
npx tsc --noEmit -p tsconfig.app.json
npm run build
```

Expected: both succeed with no errors.

- [ ] **Step 4: Run tests**

```bash
npm test
```

Expected: all previous tests still pass.

- [ ] **Step 5: Commit + push**

```bash
cd ..
git add frontend/src/features/countries/CountryDetailPage.tsx frontend/src/routes.tsx
git commit -m "feat(frontend): CountryDetailPage with driver breakdown + history charts"
git push
```

---

## Task 10: Manual end-to-end smoke (user)

Not a code task — boot the stack and click through in the browser.

- [ ] **Step 1: Boot backend**

In one PowerShell terminal:

```powershell
cd "C:\Users\APR\OneDrive - Anchor Point Risk (Pty) Ltd\Desktop\VS_CODE_REPOSITORY\country-risk-model\backend"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

Expected: `Uvicorn running on http://127.0.0.1:8000`.

- [ ] **Step 2: Boot frontend**

In a second PowerShell terminal:

```powershell
cd "C:\Users\APR\OneDrive - Anchor Point Risk (Pty) Ltd\Desktop\VS_CODE_REPOSITORY\country-risk-model\frontend"
npm run dev
```

Expected: Vite starts at `http://localhost:5173`.

- [ ] **Step 3: Sign in**

Browser → `http://localhost:5173`. Login as `owner@anchorpointrisk.local` with the password you set in Plan 1 Task 8. You should land at `/countries`.

- [ ] **Step 4: Verify the list**

On the countries page:
- You should see ~159 countries total.
- About 60 should have a `latest_final_score` shown (matches Plan 4's compute result).
- Sort by "Latest score" — top entries should be the highest-scoring.
- Filter by "USA" — should narrow to 1–2 entries.

- [ ] **Step 5: Click into a detail page**

Click any country with a score (e.g. `UNITED STATES`). You should see:
- Headline panel with final_score (3 decimal), segment (HIGH), snapshot name, as-of date.
- Driver breakdown chart with a horizontal bar per variable — should be 5 bars (our subset model has 5 variables).
- History chart — will only have 1 data point since we only have one published snapshot. Expected.

Click a country without a score (e.g. pick one showing `—` in the list). The detail page should show "No published score" rather than erroring.

- [ ] **Step 6: PD/LGD consumer check (optional)**

In a terminal, test the service-account-style direct API call:

```powershell
# Get a token from the browser DevTools → Local Storage → your supabase project's auth-token entry → access_token field. Paste it into $TOKEN.
$TOKEN = "eyJhbGciOi..."  # your copied access_token

curl.exe -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/v1/countries/USA/score | ConvertFrom-Json | ConvertTo-Json -Depth 5
```

Expected: JSON with `snapshot_id`, `model_version_high`, `published_at`, `as_of_date`, and the score fields. This is exactly the shape the PD/LGD service account would get when it later has its own token.

- [ ] **Step 7: Reply with confirmation** — country list works, detail page renders, both charts show, and `/v1/countries/{iso3}/score` returns the audit-grade shape.

---

## Task 11: Tag plan-5-public-api-ui

- [ ] **Step 1: Final test run**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest -v
```

Expected: 47 passed, 5 deselected.

```bash
cd ../frontend
npm test
```

Expected: all frontend tests pass (should be 4+).

- [ ] **Step 2: Tag**

```bash
cd ..
git tag -a plan-5-public-api-ui -m "Plan 5 complete: /v1/* public read API + country list/detail UI with charts"
git push --tags
```

- [ ] **Step 3: Verify on GitHub**

https://github.com/henrye1/country-risk-model/tags — `plan-5-public-api-ui` should appear.

---

## Validation Checklist (end-of-plan)

- [ ] `backend/app/repositories/published_score.py` exists with all 8+ methods.
- [ ] 7 new public endpoints registered under `/v1/*` and tested at route level.
- [ ] `pytest -v`: 47 passed.
- [ ] Frontend `CountryListPage` shows score column, filter, sort — tests pass.
- [ ] Frontend `CountryDetailPage` renders at `/countries/:iso3` with driver + history charts.
- [ ] Manual smoke: scored country shows charts; unscored country shows "No published score" without error.
- [ ] `/v1/countries/{iso3}/score` response includes `snapshot_id`, `model_version_*`, `as_of_date`, `published_at` — the audit-grade shape PD/LGD consumers need.
- [ ] Tag `plan-5-public-api-ui` pushed to GitHub.

When all ticked: ready for **Plan 6 — Client features** (watchlists, simulate, in-app alerts).
