# Plan — Model Training Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring model training into the app as a first-class workflow. After this plan, an internal owner can: trigger a retrain from the admin UI, download a CSV/Excel diagnostic of predicted-vs-target on training data for prototype-validation, approve the new model, then activate it (which auto-retires the previous active model in that segment).

**Architecture:** Extend `model_version_status` enum from `(active, retired)` to `(pending_review, approved, active, retired)` with DB-enforced transitions. Add a training service that wraps the existing `domain/training.train_model_for_segment` and persists new versions as `pending_review`. New admin endpoints for train/list/detail/approve/activate/retire/diagnostics-download. New React pages for the lifecycle. The CLI `train_baseline.py` continues to work — it just defaults to `pending_review` like the API path.

**Tech Stack:** Python 3.12 (FastAPI, openpyxl for XLSX), Supabase Postgres, React + TypeScript + TanStack Query.

**Precondition:** Plan 5 tagged `plan-5-public-api-ui`. Blending Ridge fix from `b6a25cf` is in. Repo at `C:/Users/APR/OneDrive - Anchor Point Risk (Pty) Ltd/Desktop/VS_CODE_REPOSITORY/country-risk-model/`.

---

## Design notes (read first)

### Status flow

```
pending_review  ─approve→  approved  ─activate→  active  ─supersede→  retired
       │                        │                                          ▲
       └──────retire────────────┴──────retire──────────────────────────────┘
```

- New trainings always start `pending_review`.
- Owner-only: `approve`, `activate`, `retire`.
- Two-step gate: must be `approved` before `activate`.
- Auto-retire on activate: when a model in segment X becomes `active`, all *other* `active` models in segment X auto-flip to `retired` (DB trigger).
- Snapshot compute already filters by `status='active'` (existing behaviour preserved — `pending_review` and `approved` models are invisible to it).

### Target variable sourcing — explicitly out of scope

This plan trains from the same `supabase/seeds/training_*.csv` files used today. Adding a UI for analysts to upload fresh **target** values (so retraining can use newer data than 2011) is a separate plan. We acknowledge this limitation in the Train form's help text.

### Diagnostic CSV / XLSX columns

Same shape as today's `model_diagnostics.py`, persisted on the fly when downloaded:

```
iso3, name, target, predicted, residual,
quant_score, qual_score,
<var>_raw, <var>_contribution, ...   # one pair per driver
```

Excel adds a "Summary" sheet with overall stats (n, correlation, R², MAE, target/pred mean/std) plus the per-row data on a second sheet named "Rows".

### What this plan does NOT do

- Cross-validated alpha tuning (separate enhancement)
- Multi-year aggregate features (separate enhancement)
- Target variable upload UI (separate plan)
- Model comparison (A/B view of two versions side-by-side) — could be a follow-on
- Background worker for long training runs (current is 2-5 sec; sync is fine)

---

## File Structure After This Plan

```
country-risk-model/
├── backend/
│   ├── app/
│   │   ├── services/
│   │   │   └── training.py            # NEW — wraps domain.training, handles diagnostics gen
│   │   ├── api/
│   │   │   └── admin.py               # MODIFY — add 7 model endpoints + role guard
│   │   ├── repositories/
│   │   │   └── model_version.py       # MODIFY — list/get/transitions, default status=pending_review
│   │   ├── schemas/
│   │   │   └── model.py               # MODIFY — request/response models for the lifecycle
│   │   └── core/
│   │       └── auth.py                # MODIFY — add `require_owner` helper
│   ├── scripts/
│   │   └── train_baseline.py          # MODIFY — train as pending_review (one-line change)
│   └── tests/
│       └── api/
│           └── test_admin_models.py   # NEW
├── frontend/
│   └── src/
│       ├── lib/
│       │   └── api.ts                 # MODIFY — add model lifecycle methods
│       ├── features/
│       │   └── admin/                 # NEW
│       │       ├── ModelsListPage.tsx
│       │       ├── TrainModelPage.tsx
│       │       └── ModelDetailPage.tsx
│       ├── routes.tsx                 # MODIFY — add 3 routes + AppShell nav link
│       └── components/
│           └── AppShell.tsx           # MODIFY — show "Admin → Models" link for internal users
└── supabase/
    └── migrations/
        └── 20260420000004_model_status_lifecycle.sql   # NEW
```

---

## Task 1: Migration — extended status enum + transition triggers

**Files:**
- Create: `supabase/migrations/20260420000004_model_status_lifecycle.sql`

- [ ] **Step 1: Write the migration**

```sql
-- 20260420000004_model_status_lifecycle.sql
-- Extend model_version_status from (active, retired) to four states with
-- enforced transitions and auto-retire-others on activation.

-- 1) Add the new enum values. Postgres requires these to be added in
-- separate statements outside any transaction that uses them.
alter type model_version_status add value if not exists 'pending_review' before 'active';
alter type model_version_status add value if not exists 'approved' before 'active';

-- 2) Default new rows to 'pending_review' (was 'active').
alter table model_versions alter column status set default 'pending_review';

-- 3) Status transition guard: only allow draft→approved, approved→active,
-- and any-status→retired. Reject everything else.
create or replace function app.enforce_model_version_status_transitions()
returns trigger
language plpgsql
as $$
begin
  -- Allow INSERT freely (default is now pending_review; CLI/script may also seed 'active' historically).
  if tg_op = 'INSERT' then
    return new;
  end if;

  -- No-op updates (status unchanged) are allowed.
  if old.status = new.status then
    return new;
  end if;

  -- Allowed transitions
  if old.status = 'pending_review' and new.status in ('approved', 'retired') then
    return new;
  end if;
  if old.status = 'approved' and new.status in ('active', 'retired') then
    return new;
  end if;
  if old.status = 'active' and new.status = 'retired' then
    return new;
  end if;

  raise exception 'invalid model_version status transition: % → %', old.status, new.status
    using errcode = 'check_violation';
end;
$$;

create trigger model_versions_status_transitions
before insert or update on model_versions
for each row execute function app.enforce_model_version_status_transitions();

-- 4) Auto-retire other active models in the same segment when a model becomes active.
-- Runs AFTER UPDATE so the trigger above won't reject our own update of siblings.
create or replace function app.retire_other_active_in_segment()
returns trigger
language plpgsql
as $$
begin
  if new.status = 'active' and (old.status is distinct from 'active') then
    update model_versions
      set status = 'retired'
      where segment = new.segment
        and id <> new.id
        and status = 'active';
  end if;
  return new;
end;
$$;

create trigger model_versions_auto_retire_on_activate
after update on model_versions
for each row execute function app.retire_other_active_in_segment();
```

- [ ] **Step 2: Apply**

```bash
/c/Users/APR/scoop/shims/supabase.exe db push --linked
```

Expected: `Applying migration 20260420000004_model_status_lifecycle.sql... Finished supabase db push.`

- [ ] **Step 3: Verify idempotency**

```bash
/c/Users/APR/scoop/shims/supabase.exe db push --linked
```

Expected: `Remote database is up to date.`

- [ ] **Step 4: Sanity-check existing 'active' models still work**

In Supabase SQL editor:

```sql
SELECT segment, status, count(*) FROM model_versions GROUP BY segment, status;
```

Expected: 4 rows (HIGH active, LOW active from earlier — both untouched).

- [ ] **Step 5: Commit**

```bash
cd "C:/Users/APR/OneDrive - Anchor Point Risk (Pty) Ltd/Desktop/VS_CODE_REPOSITORY/country-risk-model/"
git add supabase/migrations/20260420000004_model_status_lifecycle.sql
git commit -m "feat(db): model_version_status lifecycle (pending_review→approved→active) + auto-retire trigger"
git push
```

---

## Task 2: Default training to `pending_review`

**Files:**
- Modify: `backend/app/repositories/model_version.py` — change save() default
- Modify: `backend/scripts/train_baseline.py` — pass status explicitly

- [ ] **Step 1: Edit `backend/app/repositories/model_version.py` — change the insert payload**

Use Edit. Find:

```python
        inserted = self._client.table("model_versions").insert({
            "segment": trained.segment,
            "training_notes": training_notes,
            "training_data_hash": trained.training_data_hash,
            "fit_metrics_json": trained.fit_metrics,
            "status": "active",
        }).execute()
```

Replace with:

```python
        inserted = self._client.table("model_versions").insert({
            "segment": trained.segment,
            "training_notes": training_notes,
            "training_data_hash": trained.training_data_hash,
            "fit_metrics_json": trained.fit_metrics,
            "status": "pending_review",
        }).execute()
```

- [ ] **Step 2: Run tests — no regressions**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest -v 2>&1 | tail -5
```

Expected: 49 passed, 5 deselected.

- [ ] **Step 3: Commit**

```bash
cd ..
git add backend/app/repositories/model_version.py
git commit -m "fix(backend): newly trained models default to pending_review status"
git push
```

(No change to `train_baseline.py` needed — it goes through the same repository.save method.)

---

## Task 3: Owner-role guard

**Files:**
- Modify: `backend/app/api/admin.py` — add `_require_owner` helper

- [ ] **Step 1: Edit `backend/app/api/admin.py`**

Use Edit. Find:

```python
def _require_internal(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Role gate: the caller must belong to an organisation with status='internal'.
    We determine this by asking the service_client to read the caller's membership
    (bypasses RLS for this check).
    """
```

Replace with:

```python
def _require_internal(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Role gate: the caller must belong to an organisation with status='internal'."""
```

(Just trim the helper docstring — we'll add `_require_owner` after the existing function.)

Then find the closing of `_require_internal` (the last `return user`) and immediately after it add:

```python


def _require_owner(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Role gate: caller must be an internal_owner (the only role allowed to
    train, approve, activate, or retire models)."""
    client = service_client()
    resp = (
        client.table("memberships")
        .select("role, organisations(status)")
        .eq("user_id", str(user.user_id))
        .limit(1)
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="no membership")
    row = resp.data[0]
    org_status = (row.get("organisations") or {}).get("status")
    if org_status != "internal" or row.get("role") != "internal_owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="internal_owner role required")
    return user
```

- [ ] **Step 2: Smoke import**

```bash
cd backend
./.venv/Scripts/python.exe -c "from app.api.admin import _require_owner; print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Tests still pass**

```bash
./.venv/Scripts/python.exe -m pytest -v 2>&1 | tail -5
```

Expected: 49 passed.

- [ ] **Step 4: Commit**

```bash
cd ..
git add backend/app/api/admin.py
git commit -m "feat(api): _require_owner guard for sensitive admin actions"
git push
```

---

## Task 4: Diagnostics generator (CSV + XLSX)

**Files:**
- Create: `backend/app/services/training_diagnostics.py`

The generator takes a `TrainedModel` and a list of training rows (CSV-loaded dicts) and produces:
- A `bytes` CSV
- A `bytes` XLSX with two sheets ("Summary" + "Rows")

- [ ] **Step 1: Create `backend/app/services/training_diagnostics.py`**

```python
"""Generate predicted-vs-target diagnostics for a trained model on its training data.

Produces CSV + XLSX byte payloads suitable for HTTP file responses.
Same logic as `scripts/model_diagnostics.py` but factored for reuse.
"""
from __future__ import annotations
from dataclasses import dataclass
from io import BytesIO, StringIO
from typing import Iterable

import csv as csv_mod

import numpy as np
from openpyxl import Workbook
from sklearn.metrics import mean_absolute_error, r2_score

from app.domain.scoring import score_country
from app.domain.types import DriverInput, TrainedModel


@dataclass
class DiagnosticRow:
    iso3: str
    name: str
    target: float
    predicted: float
    residual: float
    quant_score: float
    qual_score: float
    drivers: dict[str, dict[str, float | None]]  # {var_code: {raw, contribution}}


@dataclass
class DiagnosticSummary:
    n: int
    correlation: float
    r2: float
    mae: float
    target_mean: float
    target_std: float
    target_min: float
    target_max: float
    pred_mean: float
    pred_std: float
    pred_min: float
    pred_max: float


def _score_training_rows(
    model: TrainedModel,
    rows: Iterable[dict],
) -> list[DiagnosticRow]:
    """Score each training row against `model`. Skip rows with missing target/drivers."""
    out: list[DiagnosticRow] = []
    required = tuple(model.quant_variable_codes) + tuple(model.qual_variable_codes)
    for r in rows:
        iso3 = r.get("iso3", "").strip()
        name = r.get("name", "").strip()
        target_str = r.get("eiu_score", "").strip()
        if not iso3 or not target_str:
            continue
        target = float(target_str)
        drivers: dict[str, float] = {}
        missing = False
        for code in required:
            v = r.get(code, "").strip()
            if not v:
                missing = True
                break
            drivers[code] = float(v)
        if missing:
            continue

        inputs = tuple(DriverInput(variable_code=c, raw_value=drivers[c]) for c in required)
        result = score_country(iso3=iso3, model=model, inputs=inputs)

        driver_payload: dict[str, dict[str, float | None]] = {}
        for ds in result.driver_scores:
            driver_payload[ds.variable_code] = {
                "raw": ds.raw_value,
                "contribution": ds.contribution,
            }

        out.append(DiagnosticRow(
            iso3=iso3,
            name=name,
            target=target,
            predicted=result.final_score,
            residual=target - result.final_score,
            quant_score=result.quant_score,
            qual_score=result.qual_score,
            drivers=driver_payload,
        ))
    return out


def _summary(rows: list[DiagnosticRow]) -> DiagnosticSummary:
    if not rows:
        return DiagnosticSummary(0, float("nan"), float("nan"), float("nan"),
                                 float("nan"), float("nan"), float("nan"), float("nan"),
                                 float("nan"), float("nan"), float("nan"), float("nan"))
    targets = np.array([r.target for r in rows])
    preds = np.array([r.predicted for r in rows])
    return DiagnosticSummary(
        n=len(rows),
        correlation=float(np.corrcoef(targets, preds)[0, 1]) if len(targets) > 1 else float("nan"),
        r2=float(r2_score(targets, preds)) if len(targets) > 1 else float("nan"),
        mae=float(mean_absolute_error(targets, preds)),
        target_mean=float(targets.mean()),
        target_std=float(targets.std()),
        target_min=float(targets.min()),
        target_max=float(targets.max()),
        pred_mean=float(preds.mean()),
        pred_std=float(preds.std()),
        pred_min=float(preds.min()),
        pred_max=float(preds.max()),
    )


def _ordered_driver_codes(model: TrainedModel) -> list[str]:
    return list(model.quant_variable_codes) + list(model.qual_variable_codes)


def _row_to_flat(row: DiagnosticRow, driver_codes: list[str]) -> dict[str, object]:
    flat: dict[str, object] = {
        "iso3": row.iso3,
        "name": row.name,
        "target": row.target,
        "predicted": row.predicted,
        "residual": row.residual,
        "quant_score": row.quant_score,
        "qual_score": row.qual_score,
    }
    for code in driver_codes:
        d = row.drivers.get(code, {})
        flat[f"{code}_raw"] = d.get("raw")
        flat[f"{code}_contribution"] = d.get("contribution")
    return flat


def generate_csv(model: TrainedModel, training_rows: Iterable[dict]) -> bytes:
    rows = _score_training_rows(model, training_rows)
    driver_codes = _ordered_driver_codes(model)
    fieldnames = ["iso3", "name", "target", "predicted", "residual",
                  "quant_score", "qual_score"]
    for code in driver_codes:
        fieldnames += [f"{code}_raw", f"{code}_contribution"]

    buf = StringIO()
    w = csv_mod.DictWriter(buf, fieldnames=fieldnames)
    w.writeheader()
    for r in rows:
        w.writerow(_row_to_flat(r, driver_codes))
    return buf.getvalue().encode("utf-8")


def generate_xlsx(model: TrainedModel, training_rows: Iterable[dict]) -> bytes:
    rows = _score_training_rows(model, training_rows)
    summary = _summary(rows)
    driver_codes = _ordered_driver_codes(model)

    wb = Workbook()
    # Summary sheet
    s_ws = wb.active
    s_ws.title = "Summary"
    s_ws.append(["Metric", "Value"])
    for label, value in [
        ("segment", model.segment),
        ("quant_variables", ", ".join(model.quant_variable_codes)),
        ("qual_variables", ", ".join(model.qual_variable_codes)),
        ("n", summary.n),
        ("correlation", summary.correlation),
        ("r2", summary.r2),
        ("mae", summary.mae),
        ("target_mean", summary.target_mean),
        ("target_std", summary.target_std),
        ("target_min", summary.target_min),
        ("target_max", summary.target_max),
        ("pred_mean", summary.pred_mean),
        ("pred_std", summary.pred_std),
        ("pred_min", summary.pred_min),
        ("pred_max", summary.pred_max),
        ("final_intercept", model.final_intercept),
        ("final_w_quant", model.final_w_quant),
        ("final_w_qual", model.final_w_qual),
    ]:
        s_ws.append([label, value])

    # Rows sheet
    r_ws = wb.create_sheet("Rows")
    fieldnames = ["iso3", "name", "target", "predicted", "residual",
                  "quant_score", "qual_score"]
    for code in driver_codes:
        fieldnames += [f"{code}_raw", f"{code}_contribution"]
    r_ws.append(fieldnames)
    for r in rows:
        flat = _row_to_flat(r, driver_codes)
        r_ws.append([flat.get(k) for k in fieldnames])

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
```

- [ ] **Step 2: Smoke-import**

```bash
cd backend
./.venv/Scripts/python.exe -c "from app.services.training_diagnostics import generate_csv, generate_xlsx; print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
cd ..
git add backend/app/services/training_diagnostics.py
git commit -m "feat(services): training diagnostics CSV + XLSX generators"
git push
```

---

## Task 5: Training service that wraps the domain trainer

**Files:**
- Create: `backend/app/services/training.py`

The service is a thin orchestrator: load training CSV → call `train_model_for_segment` → persist as `pending_review` → return the new id + fit metrics.

- [ ] **Step 1: Create `backend/app/services/training.py`**

```python
"""Training service: wraps domain.train_model_for_segment with CSV loading + persistence."""
from __future__ import annotations
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID

from app.domain.training import train_model_for_segment
from app.repositories.model_version import ModelVersionRepository

REPO_ROOT = Path(__file__).resolve().parents[3]
SEEDS = REPO_ROOT / "supabase" / "seeds"

Segment = Literal["HIGH", "LOW", "NODATA"]


@dataclass
class TrainResult:
    model_version_id: UUID
    segment: str
    fit_metrics: dict[str, float]
    n_training_rows: int


def _read_csv(
    path: Path,
    quant_codes: tuple[str, ...],
    qual_codes: tuple[str, ...],
) -> dict[str, list[float]]:
    rows = list(csv.DictReader(path.open("r", encoding="utf-8", newline="")))
    if not rows:
        raise ValueError(f"no rows in {path}")
    cols = ("eiu_score",) + quant_codes + qual_codes
    out: dict[str, list[float]] = {c: [] for c in cols}
    for r in rows:
        for c in cols:
            v = r.get(c, "").strip()
            out[c].append(float(v) if v else float("nan"))
    return out


def _csv_path_for(segment: Segment) -> Path:
    name = {"HIGH": "training_high.csv", "LOW": "training_low.csv"}.get(segment)
    if name is None:
        raise ValueError(f"no training CSV available for segment {segment}")
    return SEEDS / name


def train_segment(
    repo: ModelVersionRepository,
    segment: Segment,
    quant_codes: tuple[str, ...],
    qual_codes: tuple[str, ...],
    notes: str | None,
    n_buckets: int = 5,
    ridge_alpha: float = 1.0,
) -> TrainResult:
    csv_path = _csv_path_for(segment)
    data = _read_csv(csv_path, quant_codes, qual_codes)
    trained = train_model_for_segment(
        segment=segment,
        rows=data,
        quant_variable_codes=quant_codes,
        qual_variable_codes=qual_codes,
        n_buckets=n_buckets,
        ridge_alpha=ridge_alpha,
    )
    version_id = repo.save(trained, training_notes=notes)
    return TrainResult(
        model_version_id=version_id,
        segment=segment,
        fit_metrics=dict(trained.fit_metrics),
        n_training_rows=int(trained.fit_metrics.get("n_training_rows", 0)),
    )


def load_training_rows(segment: Segment) -> list[dict]:
    """Load the training CSV as a list of dicts (used by the diagnostics route)."""
    return list(csv.DictReader(_csv_path_for(segment).open("r", encoding="utf-8", newline="")))
```

- [ ] **Step 2: Smoke-import**

```bash
cd backend
./.venv/Scripts/python.exe -c "from app.services.training import train_segment, load_training_rows, TrainResult; print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
cd ..
git add backend/app/services/training.py
git commit -m "feat(services): training service — load csv + train + persist as pending_review"
git push
```

---

## Task 6: Model lifecycle schemas

**Files:**
- Modify: `backend/app/schemas/model.py`

- [ ] **Step 1: Replace `backend/app/schemas/model.py`**

```python
from __future__ import annotations
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field


class TrainModelRequest(BaseModel):
    segment: str  # "HIGH" | "LOW" | "NODATA"
    quant_codes: list[str] = Field(min_length=1)
    qual_codes: list[str] = Field(min_length=1)
    notes: str | None = None


class ModelVersionOut(BaseModel):
    id: UUID
    segment: str
    status: str
    trained_at: datetime
    training_notes: str | None
    training_data_hash: str
    fit_metrics_json: dict[str, float] = Field(default_factory=dict)


class TrainResultOut(BaseModel):
    model_version_id: UUID
    segment: str
    fit_metrics: dict[str, float]
    n_training_rows: int
```

- [ ] **Step 2: Smoke-import**

```bash
cd backend
./.venv/Scripts/python.exe -c "from app.schemas.model import TrainModelRequest, ModelVersionOut, TrainResultOut; print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Run tests**

```bash
./.venv/Scripts/python.exe -m pytest -v 2>&1 | tail -5
```

Expected: 49 passed.

- [ ] **Step 4: Commit**

```bash
cd ..
git add backend/app/schemas/model.py
git commit -m "feat(schemas): TrainModelRequest + ModelVersionOut + TrainResultOut"
git push
```

---

## Task 7: Repository — add list/get + status transition methods

**Files:**
- Modify: `backend/app/repositories/model_version.py`

- [ ] **Step 1: Append to `ModelVersionRepository` class**

Use Edit. Find the closing of the existing `load(self, model_version_id: UUID)` method (the last `final_w_qual=final_w_qual,)` line followed by the closing parenthesis `)`). After that closing, append these methods to the class:

```python

    def list(self) -> list[dict]:
        """All model versions, newest first."""
        resp = (
            self._client.table("model_versions")
            .select("id, segment, status, trained_at, training_notes, training_data_hash, fit_metrics_json")
            .order("trained_at", desc=True)
            .execute()
        )
        return resp.data

    def get(self, model_version_id: UUID) -> dict | None:
        resp = (
            self._client.table("model_versions")
            .select("id, segment, status, trained_at, training_notes, training_data_hash, fit_metrics_json")
            .eq("id", str(model_version_id))
            .limit(1)
            .execute()
        )
        return resp.data[0] if resp.data else None

    def set_status(self, model_version_id: UUID, new_status: str) -> dict:
        """Transition the model_version's status. The DB trigger enforces validity."""
        resp = (
            self._client.table("model_versions")
            .update({"status": new_status})
            .eq("id", str(model_version_id))
            .execute()
        )
        if not resp.data:
            raise ValueError(f"no model_version with id {model_version_id}")
        return resp.data[0]
```

- [ ] **Step 2: Smoke-import**

```bash
cd backend
./.venv/Scripts/python.exe -c "from app.repositories.model_version import ModelVersionRepository; r = ModelVersionRepository; print('list' in dir(r), 'get' in dir(r), 'set_status' in dir(r))"
```

Expected: `True True True`.

- [ ] **Step 3: Run tests**

```bash
./.venv/Scripts/python.exe -m pytest -v 2>&1 | tail -5
```

Expected: 49 passed.

- [ ] **Step 4: Commit**

```bash
cd ..
git add backend/app/repositories/model_version.py
git commit -m "feat(backend): model_version repo — list/get/set_status methods"
git push
```

---

## Task 8: Admin endpoints — train + list + get + transitions + diagnostics download

**Files:**
- Modify: `backend/app/api/admin.py`

Seven new routes:
- `POST /admin/model-versions` — train a new version (owner only)
- `GET  /admin/model-versions` — list all (internal)
- `GET  /admin/model-versions/{id}` — get one (internal)
- `POST /admin/model-versions/{id}/approve` — pending_review → approved (owner)
- `POST /admin/model-versions/{id}/activate` — approved → active (owner; auto-retires others)
- `POST /admin/model-versions/{id}/retire` — any → retired (owner)
- `GET  /admin/model-versions/{id}/diagnostics.csv` — CSV download (internal)
- `GET  /admin/model-versions/{id}/diagnostics.xlsx` — XLSX download (internal)

- [ ] **Step 1: Update imports at the top of `backend/app/api/admin.py`**

Find:

```python
from app.services.snapshot import SnapshotService
```

After it, add:

```python
from fastapi import Response
from app.repositories.model_version import ModelVersionRepository
from app.schemas.model import ModelVersionOut, TrainModelRequest, TrainResultOut
from app.services.training import load_training_rows, train_segment
from app.services.training_diagnostics import generate_csv, generate_xlsx
```

- [ ] **Step 2: Append the route handlers at the end of `backend/app/api/admin.py`**

```python


# --- Model lifecycle ---

@router.post("/model-versions", response_model=TrainResultOut, status_code=status.HTTP_201_CREATED)
def train_model(
    req: TrainModelRequest,
    user: CurrentUser = Depends(_require_owner),
) -> TrainResultOut:
    repo = ModelVersionRepository(service_client())
    try:
        result = train_segment(
            repo=repo,
            segment=req.segment,  # type: ignore[arg-type]
            quant_codes=tuple(req.quant_codes),
            qual_codes=tuple(req.qual_codes),
            notes=req.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return TrainResultOut(
        model_version_id=result.model_version_id,
        segment=result.segment,
        fit_metrics=result.fit_metrics,
        n_training_rows=result.n_training_rows,
    )


@router.get("/model-versions", response_model=list[ModelVersionOut])
def list_models(user: CurrentUser = Depends(_require_internal)) -> list[ModelVersionOut]:
    repo = ModelVersionRepository(service_client())
    return [ModelVersionOut(**r) for r in repo.list()]


@router.get("/model-versions/{model_version_id}", response_model=ModelVersionOut)
def get_model(
    model_version_id: UUID,
    user: CurrentUser = Depends(_require_internal),
) -> ModelVersionOut:
    repo = ModelVersionRepository(service_client())
    row = repo.get(model_version_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="model_version not found")
    return ModelVersionOut(**row)


@router.post("/model-versions/{model_version_id}/approve", response_model=ModelVersionOut)
def approve_model(
    model_version_id: UUID,
    user: CurrentUser = Depends(_require_owner),
) -> ModelVersionOut:
    repo = ModelVersionRepository(service_client())
    try:
        row = repo.set_status(model_version_id, "approved")
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ModelVersionOut(**row)


@router.post("/model-versions/{model_version_id}/activate", response_model=ModelVersionOut)
def activate_model(
    model_version_id: UUID,
    user: CurrentUser = Depends(_require_owner),
) -> ModelVersionOut:
    repo = ModelVersionRepository(service_client())
    try:
        row = repo.set_status(model_version_id, "active")
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ModelVersionOut(**row)


@router.post("/model-versions/{model_version_id}/retire", response_model=ModelVersionOut)
def retire_model(
    model_version_id: UUID,
    user: CurrentUser = Depends(_require_owner),
) -> ModelVersionOut:
    repo = ModelVersionRepository(service_client())
    try:
        row = repo.set_status(model_version_id, "retired")
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ModelVersionOut(**row)


@router.get("/model-versions/{model_version_id}/diagnostics.csv")
def download_diagnostics_csv(
    model_version_id: UUID,
    user: CurrentUser = Depends(_require_internal),
) -> Response:
    repo = ModelVersionRepository(service_client())
    row = repo.get(model_version_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="model_version not found")
    model = repo.load(model_version_id)
    rows = load_training_rows(row["segment"])
    body = generate_csv(model, rows)
    fname = f"diagnostics_{row['segment']}_{model_version_id}.csv"
    return Response(
        content=body,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/model-versions/{model_version_id}/diagnostics.xlsx")
def download_diagnostics_xlsx(
    model_version_id: UUID,
    user: CurrentUser = Depends(_require_internal),
) -> Response:
    repo = ModelVersionRepository(service_client())
    row = repo.get(model_version_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="model_version not found")
    model = repo.load(model_version_id)
    rows = load_training_rows(row["segment"])
    body = generate_xlsx(model, rows)
    fname = f"diagnostics_{row['segment']}_{model_version_id}.xlsx"
    return Response(
        content=body,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
```

- [ ] **Step 3: Smoke-check routes**

```bash
cd backend
./.venv/Scripts/python.exe -c "from app.main import create_app; app = create_app(); print(sorted([r.path for r in app.routes if hasattr(r, 'path') and 'model-versions' in r.path]))"
```

Expected: 7 paths (model-versions, /{id}, /{id}/approve, /{id}/activate, /{id}/retire, /{id}/diagnostics.csv, /{id}/diagnostics.xlsx).

- [ ] **Step 4: Run tests**

```bash
./.venv/Scripts/python.exe -m pytest -v 2>&1 | tail -5
```

Expected: 49 passed.

- [ ] **Step 5: Commit**

```bash
cd ..
git add backend/app/api/admin.py
git commit -m "feat(api): admin model-versions endpoints (train/list/get/approve/activate/retire/download)"
git push
```

---

## Task 9: Backend tests for the new lifecycle

**Files:**
- Create: `backend/tests/api/test_admin_models.py`

- [ ] **Step 1: Write the test file**

```python
from __future__ import annotations
import time
from uuid import UUID, uuid4
import pytest
from jose import jwt
from fastapi.testclient import TestClient

JWT_SECRET = "test-jwt-secret"


def _token(user_id: str = "11111111-1111-1111-1111-111111111111") -> str:
    payload = {
        "sub": user_id,
        "email": "owner@anchorpointrisk.local",
        "aud": "authenticated",
        "role": "authenticated",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


class _FakeRepo:
    def __init__(self) -> None:
        self.rows: dict[UUID, dict] = {}
        self.created_id = uuid4()

    def list(self):
        return list(self.rows.values())

    def get(self, mid):
        return self.rows.get(UUID(str(mid)))

    def set_status(self, mid, new_status):
        row = self.rows[UUID(str(mid))]
        row["status"] = new_status
        return row

    def save(self, trained, training_notes=None):
        new = {
            "id": str(self.created_id),
            "segment": trained.segment,
            "status": "pending_review",
            "trained_at": "2026-04-20T13:00:00Z",
            "training_notes": training_notes,
            "training_data_hash": trained.training_data_hash,
            "fit_metrics_json": dict(trained.fit_metrics),
        }
        self.rows[self.created_id] = new
        return self.created_id


@pytest.fixture
def client(monkeypatch):
    from app.main import create_app
    from app.api import admin
    from app.schemas.user import CurrentUser
    from uuid import UUID

    app = create_app()

    async def _override_owner():
        return CurrentUser(
            user_id=UUID("11111111-1111-1111-1111-111111111111"),
            email="owner@anchorpointrisk.local",
            raw_jwt="test",
        )

    async def _override_internal():
        return CurrentUser(
            user_id=UUID("11111111-1111-1111-1111-111111111111"),
            email="analyst@anchorpointrisk.local",
            raw_jwt="test",
        )

    app.dependency_overrides[admin._require_owner] = _override_owner
    app.dependency_overrides[admin._require_internal] = _override_internal

    fake_repo = _FakeRepo()
    monkeypatch.setattr("app.api.admin.ModelVersionRepository", lambda _client: fake_repo)
    monkeypatch.setattr("app.api.admin.service_client", lambda: object())

    # Patch train_segment to bypass real CSV/sklearn work
    from app.services.training import TrainResult

    def _fake_train(*args, **kwargs):
        return TrainResult(
            model_version_id=fake_repo.created_id,
            segment=kwargs.get("segment", "HIGH"),
            fit_metrics={"r2": 0.05, "rmse": 0.9, "n_training_rows": 50.0},
            n_training_rows=50,
        )

    # Inject a fake row into the repo so transitions/get/list have something to work with
    fake_repo.rows[fake_repo.created_id] = {
        "id": str(fake_repo.created_id),
        "segment": "HIGH",
        "status": "pending_review",
        "trained_at": "2026-04-20T13:00:00Z",
        "training_notes": "test",
        "training_data_hash": "deadbeef" * 8,
        "fit_metrics_json": {"r2": 0.05},
    }

    monkeypatch.setattr("app.api.admin.train_segment", _fake_train)
    return TestClient(app), fake_repo


def test_list_models(client):
    c, _ = client
    r = c.get("/admin/model-versions", headers={"Authorization": f"Bearer {_token()}"})
    assert r.status_code == 200
    assert len(r.json()) >= 1


def test_get_model_404(client):
    c, _ = client
    r = c.get(f"/admin/model-versions/{uuid4()}", headers={"Authorization": f"Bearer {_token()}"})
    assert r.status_code == 404


def test_train_returns_201_and_pending_review(client):
    c, repo = client
    r = c.post(
        "/admin/model-versions",
        headers={"Authorization": f"Bearer {_token()}"},
        json={
            "segment": "HIGH",
            "quant_codes": ["gdp_capita"],
            "qual_codes": ["pr"],
            "notes": "test",
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["segment"] == "HIGH"
    assert "fit_metrics" in body


def test_approve_then_activate_transitions(client):
    c, repo = client
    mid = repo.created_id
    r1 = c.post(f"/admin/model-versions/{mid}/approve", headers={"Authorization": f"Bearer {_token()}"})
    assert r1.status_code == 200
    assert r1.json()["status"] == "approved"

    r2 = c.post(f"/admin/model-versions/{mid}/activate", headers={"Authorization": f"Bearer {_token()}"})
    assert r2.status_code == 200
    assert r2.json()["status"] == "active"


def test_retire_works_from_pending(client):
    c, repo = client
    mid = repo.created_id
    r = c.post(f"/admin/model-versions/{mid}/retire", headers={"Authorization": f"Bearer {_token()}"})
    assert r.status_code == 200
    assert r.json()["status"] == "retired"
```

- [ ] **Step 2: Run**

```bash
cd backend
./.venv/Scripts/python.exe -m pytest tests/api/test_admin_models.py -v
```

Expected: `5 passed`.

- [ ] **Step 3: Full suite**

```bash
./.venv/Scripts/python.exe -m pytest -v 2>&1 | tail -5
```

Expected: 54 passed, 5 deselected.

- [ ] **Step 4: Commit**

```bash
cd ..
git add backend/tests/api/test_admin_models.py
git commit -m "test(api): admin model-versions lifecycle tests"
git push
```

---

## Task 10: Frontend API client extensions

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Append to `frontend/src/lib/api.ts`**

Open the file, find the closing of the `api` object (the line with `listSnapshots: () => request("/v1/snapshots", z.array(PublishedSnapshot)),` and the following `};`). REPLACE the closing `};` with the extended version, then add the new schemas + helpers AFTER the closing brace.

Use Edit. Find:

```ts
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
```

Replace with:

```ts
// --- Model versions (admin) ---

export const ModelVersion = z.object({
  id: z.string().uuid(),
  segment: z.string(),
  status: z.string(),
  trained_at: z.string(),
  training_notes: z.string().nullable(),
  training_data_hash: z.string(),
  fit_metrics_json: z.record(z.string(), z.number()).default({}),
});
export type ModelVersion = z.infer<typeof ModelVersion>;

export const TrainResult = z.object({
  model_version_id: z.string().uuid(),
  segment: z.string(),
  fit_metrics: z.record(z.string(), z.number()),
  n_training_rows: z.number(),
});
export type TrainResult = z.infer<typeof TrainResult>;

async function downloadBinary(path: string, filename: string): Promise<void> {
  const headers = { ...(await (async () => {
    const { data } = await supabase.auth.getSession();
    return data.session ? { Authorization: `Bearer ${data.session.access_token}` } : {};
  })()) };
  const res = await fetch(`${API_BASE}${path}`, { headers });
  if (!res.ok) throw new ApiError(res.status, res.statusText);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

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

  // Model lifecycle
  listModels: () => request("/admin/model-versions", z.array(ModelVersion)),
  getModel: (id: string) => request(`/admin/model-versions/${id}`, ModelVersion),
  trainModel: (body: { segment: string; quant_codes: string[]; qual_codes: string[]; notes?: string }) =>
    request("/admin/model-versions", TrainResult, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  approveModel: (id: string) =>
    request(`/admin/model-versions/${id}/approve`, ModelVersion, { method: "POST" }),
  activateModel: (id: string) =>
    request(`/admin/model-versions/${id}/activate`, ModelVersion, { method: "POST" }),
  retireModel: (id: string) =>
    request(`/admin/model-versions/${id}/retire`, ModelVersion, { method: "POST" }),
  downloadDiagnosticsCsv: (id: string, segment: string) =>
    downloadBinary(`/admin/model-versions/${id}/diagnostics.csv`, `diagnostics_${segment}_${id}.csv`),
  downloadDiagnosticsXlsx: (id: string, segment: string) =>
    downloadBinary(`/admin/model-versions/${id}/diagnostics.xlsx`, `diagnostics_${segment}_${id}.xlsx`),
};
```

- [ ] **Step 2: Typecheck**

```bash
cd frontend
npx tsc --noEmit -p tsconfig.app.json
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
cd ..
git add frontend/src/lib/api.ts
git commit -m "feat(frontend): API client extensions for model lifecycle + binary download helper"
git push
```

---

## Task 11: ModelsListPage

**Files:**
- Create: `frontend/src/features/admin/ModelsListPage.tsx`

- [ ] **Step 1: Create the file**

```tsx
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, type ModelVersion } from "../../lib/api";

const STATUS_STYLES: Record<string, string> = {
  active: "bg-emerald-100 text-emerald-800",
  approved: "bg-blue-100 text-blue-800",
  pending_review: "bg-amber-100 text-amber-800",
  retired: "bg-slate-100 text-slate-500",
};

function StatusBadge({ status }: { status: string }) {
  const cls = STATUS_STYLES[status] ?? "bg-slate-100 text-slate-700";
  return <span className={`rounded px-2 py-0.5 text-xs font-medium ${cls}`}>{status}</span>;
}

export function ModelsListPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["model-versions"],
    queryFn: api.listModels,
  });

  if (isLoading) return <p className="text-sm text-slate-500">Loading models...</p>;
  if (error) return <p role="alert" className="text-sm text-red-600">{(error as Error).message}</p>;

  const models = data ?? [];

  return (
    <section>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-lg font-semibold text-slate-900">Models <span className="text-sm font-normal text-slate-500">({models.length})</span></h1>
        <Link to="/admin/models/train" className="rounded bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800">
          Train new model
        </Link>
      </div>
      <div className="overflow-x-auto rounded border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-3 py-2">Segment</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Trained at</th>
              <th className="px-3 py-2">R²</th>
              <th className="px-3 py-2">RMSE</th>
              <th className="px-3 py-2">n</th>
              <th className="px-3 py-2">Notes</th>
              <th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200">
            {models.map((m: ModelVersion) => (
              <tr key={m.id} className="hover:bg-slate-50">
                <td className="px-3 py-2 font-mono text-xs">{m.segment}</td>
                <td className="px-3 py-2"><StatusBadge status={m.status} /></td>
                <td className="px-3 py-2 text-xs text-slate-500">{new Date(m.trained_at).toLocaleString()}</td>
                <td className="px-3 py-2 font-mono text-xs">{(m.fit_metrics_json["r2"] ?? 0).toFixed(3)}</td>
                <td className="px-3 py-2 font-mono text-xs">{(m.fit_metrics_json["rmse"] ?? 0).toFixed(3)}</td>
                <td className="px-3 py-2 font-mono text-xs">{m.fit_metrics_json["n_training_rows"] ?? 0}</td>
                <td className="px-3 py-2 text-xs text-slate-500">{m.training_notes ?? "—"}</td>
                <td className="px-3 py-2 text-right">
                  <Link to={`/admin/models/${m.id}`} className="text-xs text-slate-700 hover:underline">View</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
```

- [ ] **Step 2: Commit (route registration is in Task 14)**

```bash
git add frontend/src/features/admin/ModelsListPage.tsx
git commit -m "feat(frontend): ModelsListPage — list all model_versions with status + metrics"
git push
```

---

## Task 12: TrainModelPage

**Files:**
- Create: `frontend/src/features/admin/TrainModelPage.tsx`

- [ ] **Step 1: Create the file**

```tsx
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, type Variable } from "../../lib/api";

const SEGMENTS = ["HIGH", "LOW"] as const;

const DEFAULT_QUANT = ["gdp_capita", "cof", "debt_service_ratio"];
const DEFAULT_QUAL = ["rol", "pr"];

export function TrainModelPage() {
  const navigate = useNavigate();
  const variablesQ = useQuery({ queryKey: ["variables"], queryFn: api.listVariables });
  const [segment, setSegment] = useState<typeof SEGMENTS[number]>("HIGH");
  const [quant, setQuant] = useState<string[]>(DEFAULT_QUANT);
  const [qual, setQual] = useState<string[]>(DEFAULT_QUAL);
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const allVars = variablesQ.data ?? [];
  const quantOpts = allVars.filter((v) => v.is_quantitative);
  const qualOpts = allVars.filter((v) => !v.is_quantitative);

  function toggle(set: string[], code: string, setter: (v: string[]) => void) {
    setter(set.includes(code) ? set.filter((c) => c !== code) : [...set, code]);
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const result = await api.trainModel({
        segment,
        quant_codes: quant,
        qual_codes: qual,
        notes: notes || undefined,
      });
      navigate(`/admin/models/${result.model_version_id}`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="max-w-3xl space-y-6">
      <h1 className="text-lg font-semibold text-slate-900">Train new model</h1>
      <p className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
        Training uses the existing <code>supabase/seeds/training_*.csv</code> files (2011 EIU snapshot).
        Updating those targets requires a separate ingestion workflow — coming later. For now, retraining
        without changing inputs only updates <em>which variables</em> the model uses.
      </p>

      <form onSubmit={onSubmit} className="space-y-5 rounded-lg border border-slate-200 bg-white p-6">
        <label className="block text-sm">
          <span className="text-slate-700">Segment</span>
          <select
            value={segment}
            onChange={(e) => setSegment(e.target.value as typeof SEGMENTS[number])}
            className="mt-1 block w-full max-w-xs rounded border border-slate-300 px-2 py-1.5 text-sm"
          >
            {SEGMENTS.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>

        <fieldset>
          <legend className="text-sm font-medium text-slate-700">Quantitative variables ({quant.length})</legend>
          <div className="mt-2 grid grid-cols-2 gap-2 rounded border border-slate-200 p-3 text-xs">
            {quantOpts.map((v: Variable) => (
              <label key={v.code} className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={quant.includes(v.code)}
                  onChange={() => toggle(quant, v.code, setQuant)}
                />
                <span><code className="text-xs">{v.code}</code> — {v.name}</span>
              </label>
            ))}
          </div>
        </fieldset>

        <fieldset>
          <legend className="text-sm font-medium text-slate-700">Qualitative variables ({qual.length})</legend>
          <div className="mt-2 grid grid-cols-2 gap-2 rounded border border-slate-200 p-3 text-xs">
            {qualOpts.map((v: Variable) => (
              <label key={v.code} className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={qual.includes(v.code)}
                  onChange={() => toggle(qual, v.code, setQual)}
                />
                <span><code className="text-xs">{v.code}</code> — {v.name}</span>
              </label>
            ))}
          </div>
        </fieldset>

        <label className="block text-sm">
          <span className="text-slate-700">Notes (optional)</span>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="What's different about this run?"
            className="mt-1 block w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
            rows={2}
          />
        </label>

        {error && <p role="alert" className="text-sm text-red-600">{error}</p>}

        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={submitting || quant.length === 0 || qual.length === 0}
            className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {submitting ? "Training..." : "Train (5-10 sec)"}
          </button>
          <span className="text-xs text-slate-500">Will be created in <code>pending_review</code> status.</span>
        </div>
      </form>
    </section>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/features/admin/TrainModelPage.tsx
git commit -m "feat(frontend): TrainModelPage — segment + variable selection + sync train trigger"
git push
```

---

## Task 13: ModelDetailPage with downloads + lifecycle actions

**Files:**
- Create: `frontend/src/features/admin/ModelDetailPage.tsx`

- [ ] **Step 1: Create the file**

```tsx
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../lib/api";

const STATUS_STYLES: Record<string, string> = {
  active: "bg-emerald-100 text-emerald-800",
  approved: "bg-blue-100 text-blue-800",
  pending_review: "bg-amber-100 text-amber-800",
  retired: "bg-slate-100 text-slate-500",
};

function StatusBadge({ status }: { status: string }) {
  const cls = STATUS_STYLES[status] ?? "bg-slate-100 text-slate-700";
  return <span className={`rounded px-2 py-0.5 text-xs font-medium ${cls}`}>{status}</span>;
}

export function ModelDetailPage() {
  const { id = "" } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionPending, setActionPending] = useState<string | null>(null);

  const modelQ = useQuery({
    queryKey: ["model-version", id],
    queryFn: () => api.getModel(id),
    enabled: !!id,
  });

  if (modelQ.isLoading) return <p className="text-sm text-slate-500">Loading model...</p>;
  if (modelQ.error) return <p role="alert" className="text-sm text-red-600">{(modelQ.error as Error).message}</p>;
  if (!modelQ.data) return null;

  const m = modelQ.data;

  async function runAction(action: () => Promise<unknown>, label: string) {
    setActionError(null);
    setActionPending(label);
    try {
      await action();
      await qc.invalidateQueries({ queryKey: ["model-version", id] });
      await qc.invalidateQueries({ queryKey: ["model-versions"] });
    } catch (err) {
      setActionError((err as Error).message);
    } finally {
      setActionPending(null);
    }
  }

  const canApprove = m.status === "pending_review";
  const canActivate = m.status === "approved";
  const canRetire = m.status !== "retired";

  return (
    <div className="space-y-6">
      <div className="text-sm text-slate-500">
        <Link to="/admin/models" className="hover:underline">← Models</Link>
      </div>

      <header className="rounded-lg border border-slate-200 bg-white p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-semibold text-slate-900">
              {m.segment} model <StatusBadge status={m.status} />
            </h1>
            <p className="mt-1 text-sm text-slate-500">
              {m.training_notes || "No notes"} · trained {new Date(m.trained_at).toLocaleString()}
            </p>
            <p className="mt-1 font-mono text-xs text-slate-400">{m.id}</p>
          </div>
          <div className="grid grid-cols-3 gap-4 text-sm">
            <Metric label="R²" value={(m.fit_metrics_json["r2"] ?? 0).toFixed(3)} />
            <Metric label="RMSE" value={(m.fit_metrics_json["rmse"] ?? 0).toFixed(3)} />
            <Metric label="n rows" value={String(m.fit_metrics_json["n_training_rows"] ?? 0)} />
          </div>
        </div>
      </header>

      <section className="rounded-lg border border-slate-200 bg-white p-6">
        <h2 className="mb-3 text-base font-semibold text-slate-900">Validation against the prototype</h2>
        <p className="mb-3 text-sm text-slate-600">
          Download a per-country diagnostic of <strong>predicted vs target</strong> on the training data.
          Use this to compare against the original Excel prototype outputs before approving.
        </p>
        <div className="flex gap-3">
          <button
            onClick={() => api.downloadDiagnosticsCsv(m.id, m.segment)}
            className="rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50"
          >
            Download CSV
          </button>
          <button
            onClick={() => api.downloadDiagnosticsXlsx(m.id, m.segment)}
            className="rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50"
          >
            Download Excel
          </button>
        </div>
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-6">
        <h2 className="mb-3 text-base font-semibold text-slate-900">Lifecycle actions</h2>
        {actionError && <p role="alert" className="mb-3 text-sm text-red-600">{actionError}</p>}
        <div className="flex flex-wrap gap-3">
          <button
            disabled={!canApprove || actionPending !== null}
            onClick={() => runAction(() => api.approveModel(m.id), "approve")}
            className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
          >
            {actionPending === "approve" ? "Approving..." : "Approve"}
          </button>
          <button
            disabled={!canActivate || actionPending !== null}
            onClick={() => runAction(() => api.activateModel(m.id), "activate")}
            className="rounded bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
          >
            {actionPending === "activate" ? "Activating..." : "Activate"}
          </button>
          <button
            disabled={!canRetire || actionPending !== null}
            onClick={() => runAction(() => api.retireModel(m.id), "retire")}
            className="rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50 disabled:opacity-50"
          >
            {actionPending === "retire" ? "Retiring..." : "Retire"}
          </button>
        </div>
        <p className="mt-3 text-xs text-slate-500">
          Activating this model auto-retires any other active model in segment <strong>{m.segment}</strong>.
          Snapshot compute will pick up the new active model on its next run.
        </p>
      </section>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-slate-200 px-3 py-2">
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className="font-mono text-sm text-slate-900">{value}</p>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/features/admin/ModelDetailPage.tsx
git commit -m "feat(frontend): ModelDetailPage — diagnostics download + approve/activate/retire actions"
git push
```

---

## Task 14: Routes + AppShell nav link

**Files:**
- Modify: `frontend/src/routes.tsx`
- Modify: `frontend/src/components/AppShell.tsx` — add an "Admin" link

- [ ] **Step 1: Add the routes**

Edit `frontend/src/routes.tsx`. Find the existing imports block and add:

```tsx
import { ModelsListPage } from "./features/admin/ModelsListPage";
import { ModelDetailPage } from "./features/admin/ModelDetailPage";
import { TrainModelPage } from "./features/admin/TrainModelPage";
```

Then find the route entry for `/countries/:iso3` (the last existing route). Right after it (still inside the array), add:

```tsx
  {
    path: "/admin/models",
    element: (
      <RequireAuth>
        <AppShell>
          <ModelsListPage />
        </AppShell>
      </RequireAuth>
    ),
  },
  {
    path: "/admin/models/train",
    element: (
      <RequireAuth>
        <AppShell>
          <TrainModelPage />
        </AppShell>
      </RequireAuth>
    ),
  },
  {
    path: "/admin/models/:id",
    element: (
      <RequireAuth>
        <AppShell>
          <ModelDetailPage />
        </AppShell>
      </RequireAuth>
    ),
  },
```

- [ ] **Step 2: Add an "Admin → Models" link to the app shell**

Edit `frontend/src/components/AppShell.tsx`. Find the existing `<nav>` block:

```tsx
          <nav className="flex gap-3">
            <Link to="/countries" className="text-slate-700 hover:underline">Countries</Link>
          </nav>
```

Replace with:

```tsx
          <nav className="flex gap-3">
            <Link to="/countries" className="text-slate-700 hover:underline">Countries</Link>
            <Link to="/admin/models" className="text-slate-700 hover:underline">Models</Link>
          </nav>
```

- [ ] **Step 3: Typecheck + build**

```bash
cd frontend
npx tsc --noEmit -p tsconfig.app.json
npm run build 2>&1 | tail -10
```

Expected: build succeeds.

- [ ] **Step 4: Tests**

```bash
npm test 2>&1 | tail -10
```

Expected: 4 passed (existing tests; no new frontend tests in this plan).

- [ ] **Step 5: Commit**

```bash
cd ..
git add frontend/src/routes.tsx frontend/src/components/AppShell.tsx
git commit -m "feat(frontend): routes for /admin/models pages + nav link"
git push
```

---

## Task 15: Manual smoke (user)

Boot both servers (you know the drill).

- [ ] **Step 1: Sign in**

Browser → `http://localhost:5173`. Sign in as the owner user. You should see the new "Models" link in the top nav.

- [ ] **Step 2: View existing models**

Click "Models". You should see the existing 4 models (HIGH × 2, LOW × 2 from earlier plans), all status `active`.

- [ ] **Step 3: Train a new model**

Click "Train new model". Pick HIGH, leave the default 3 quant + 2 qual variables, add a note like "post-blending validation", click Train.

After 5-10 seconds, you should land on the new model's detail page. Status should be `pending_review`.

- [ ] **Step 4: Download diagnostics**

Click "Download CSV" — a file should download. Open it in Excel; you should see ~50 rows with `target`, `predicted`, `residual`, and per-driver columns.

Click "Download Excel" — a `.xlsx` file should download with two sheets: `Summary` (overall stats) and `Rows` (the same data).

**Compare predicted-vs-target against your Excel prototype outputs.** This is the validation step you asked for.

- [ ] **Step 5: Approve + activate**

On the model detail page:
- Click "Approve" → status should flip to `approved`. Approve button disables; Activate enables.
- Click "Activate" → status flips to `active`. Go back to the Models list — the previously-active HIGH model should now show as `retired` (auto-retire trigger fired).

- [ ] **Step 6: Try invalid transitions (sanity)**

Try clicking "Approve" on an `active` model — should fail with 409 (no longer in pending_review).

- [ ] **Step 7: Reply with confirmation** — diagnostics CSV/Excel downloaded successfully and the lifecycle transitions worked end-to-end.

---

## Task 16: Tag

- [ ] **Step 1: Final test runs**

```bash
cd backend && ./.venv/Scripts/python.exe -m pytest -v 2>&1 | tail -3
cd ../frontend && npm test 2>&1 | tail -5
```

Expected: 54 passed (backend); 4 passed (frontend).

- [ ] **Step 2: Tag**

```bash
cd ..
git tag -a plan-model-lifecycle -m "Model training lifecycle: pending_review → approved → active. Diagnostics CSV/Excel downloads."
git push --tags
```

---

## Validation Checklist

- [ ] Migration applied; `model_version_status` enum has 4 values; transition trigger fires on invalid moves; auto-retire trigger fires on activate.
- [ ] `pytest -v`: 54 passed.
- [ ] Browser smoke: train form works, diagnostics download both formats, approve→activate flow works, auto-retire visible in list.
- [ ] Tag `plan-model-lifecycle` pushed.

When all ticked: model lifecycle is in your hands. Then we either return to **Plan 6 (client features)** or do a **target-upload micro-plan** when you're ready to push the model further.
