# Plan 2 — Scoring Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the pure-Python scoring engine for the Country Risk Model. After this plan you can run a single command that trains a Ridge-regression model on the prototype's historical data, persists the model version (coefficients + standardisation params + bucket tables) to Supabase, and scores a country with new inputs via a deterministic Python pipeline — all unit-tested and auditable.

**Architecture:** All domain logic lives in `backend/app/domain/` as framework-free Python (no FastAPI, no Supabase imports). Repositories wrap persistence. A new migration adds four model-versioning tables. Training inputs come from two CSVs extracted from the Excel prototype (committed to `supabase/seeds/`). A CLI script `train_baseline.py` wires everything together to produce the first model version.

**Tech Stack:** Python 3.12 (scikit-learn, numpy, pandas), Supabase Postgres (new tables), pytest (unit + light integration).

**Precondition:** Plan 1 is complete (tagged `plan-1-foundation`). Backend venv exists at `backend/.venv/`. Supabase CLI linked to `country-risk-dev`. Repo is at `C:/Users/APR/OneDrive - Anchor Point Risk (Pty) Ltd/Desktop/VS_CODE_REPOSITORY/country-risk-model/`.

**Important design note (must read before starting):**

The user chose **Approach B** in brainstorming: re-train in Python using scikit-learn, not replicate Excel cell-for-cell. That means:

- We train a *fresh* Ridge regression on the prototype's 2011 training rows (Excel sheets `High_Raw` and `Low_Raw`).
- Python scores will NOT match Excel cell-for-cell. They should be **directionally consistent** (same sign of change when a driver moves) and **numerically reasonable** (similar order of magnitude).
- The test suite validates properties and invariants of the engine, not exact Excel-equivalence. A later plan (post-v1) can add a calibration step if needed.
- Variables the Excel uses but that aren't cleanly reproducible from the raw sheets in isolation (e.g. multi-year averages that need external history) are approximated from the 2011 snapshot.

---

## File Structure After This Plan

```
country-risk-model/
├── backend/
│   ├── pyproject.toml                      # modify: add scikit-learn, numpy, pandas
│   ├── scripts/
│   │   ├── extract_reference_from_xlsx.py  # existing (Plan 1)
│   │   ├── extract_training_from_xlsx.py   # NEW — produces training_high.csv + training_low.csv
│   │   └── train_baseline.py               # NEW — trains + persists v1 model
│   └── app/
│       ├── domain/                         # NEW — pure Python, framework-free
│       │   ├── __init__.py
│       │   ├── types.py                    # TrainedModel, ScoreResult, DriverInput dataclasses
│       │   ├── standardisation.py          # fit_standardiser, standardise
│       │   ├── buckets.py                  # fit_buckets, bucket_score
│       │   ├── training.py                 # fit_ridge, train_model_for_segment
│       │   └── scoring.py                  # score_country (uses all above)
│       ├── repositories/
│       │   └── model_version.py            # NEW — persist/load TrainedModel
│       └── schemas/
│           └── model.py                    # NEW — Pydantic I/O (not used by domain)
│   └── tests/
│       ├── domain/                         # NEW — mirror of app/domain/
│       │   ├── __init__.py
│       │   ├── test_standardisation.py
│       │   ├── test_buckets.py
│       │   ├── test_training.py
│       │   └── test_scoring.py
│       └── integration/
│           ├── __init__.py
│           └── test_baseline_training.py   # runs the full pipeline on prototype data
└── supabase/
    ├── migrations/
    │   └── 20260419000004_model_versions.sql   # NEW
    └── seeds/
        ├── training_high.csv               # NEW (generated)
        └── training_low.csv                # NEW (generated)
```

Rationale for the `domain/` split: each file has one responsibility (standardisation, buckets, training, scoring) and can be understood in isolation. `types.py` holds the shared dataclasses so the four domain files don't import each other in a cycle. The split keeps each file under ~150 lines.

---

## Task 1: Add ML dependencies

**Files:**
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Add `scikit-learn`, `numpy`, `pandas` to the `dependencies` list in `backend/pyproject.toml`**

Find the `dependencies = [ ... ]` block under `[project]`. After the existing entries (keeping them intact), add:

```toml
  "scikit-learn>=1.4",
  "numpy>=1.26",
  "pandas>=2.2",
```

Final block should look like:

```toml
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
  "scikit-learn>=1.4",
  "numpy>=1.26",
  "pandas>=2.2",
]
```

- [ ] **Step 2: Reinstall**

```bash
cd "C:/Users/APR/OneDrive - Anchor Point Risk (Pty) Ltd/Desktop/VS_CODE_REPOSITORY/country-risk-model/backend"
source .venv/Scripts/activate
pip install -e ".[dev]"
```

Expected: `scikit-learn`, `numpy`, `pandas` pulled in (may take 30–90s).

- [ ] **Step 3: Verify imports**

```bash
python -c "import numpy, pandas, sklearn; print(numpy.__version__, pandas.__version__, sklearn.__version__)"
```

Expected: three version strings.

- [ ] **Step 4: Commit + push**

```bash
cd ..
git add backend/pyproject.toml
git commit -m "chore(backend): add scikit-learn, numpy, pandas for scoring engine"
git push
```

---

## Task 2: Migration 4 — model version tables

**Files:**
- Create: `supabase/migrations/20260419000004_model_versions.sql`

- [ ] **Step 1: Write the migration**

```sql
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
```

- [ ] **Step 2: Apply the migration**

```bash
/c/Users/APR/scoop/shims/supabase.exe db push --linked
```

Expected: `Applying migration 20260419000004_model_versions.sql... Finished supabase db push.`

- [ ] **Step 3: Commit + push**

```bash
git add supabase/migrations/20260419000004_model_versions.sql
git commit -m "feat(db): model version tables (versions + coefficients + standardisation + buckets)"
git push
```

---

## Task 3: Extract training data from Excel prototype

**Files:**
- Create: `backend/scripts/extract_training_from_xlsx.py`
- Create: `supabase/seeds/training_high.csv` (generated)
- Create: `supabase/seeds/training_low.csv` (generated)

- [ ] **Step 1: Create `backend/scripts/extract_training_from_xlsx.py`**

```python
"""Extract 2011 training data for each HDI segment from the Excel prototype.

Outputs two CSVs in `supabase/seeds/`, one per segment. Each row is a country-year
observation used to train a Ridge regression.

Columns (in order):
  iso3, name, segment, eiu_score,
  dcpi_5_adj, nom_rir_vol, gdp_capita, growth_vol, macro_var,
  atf, dt, fdg_3yr, cof,
  pr, rol, db, sr, debt_service_ratio

The 14 driver columns match the `variables.code` seeded in Plan 1. `eiu_score` is
the target variable (existing country rating). Missing values are left blank — the
training code in Task 7 handles NaN row-dropping.
"""
from __future__ import annotations
import csv
from pathlib import Path
from openpyxl import load_workbook

REPO_ROOT = Path(__file__).resolve().parents[2]
XLSX = REPO_ROOT / "prototype" / "Country Prototype Original HDI with Ridge.xlsx"
SEEDS_DIR = REPO_ROOT / "supabase" / "seeds"

# Map our variable codes to the raw-sheet column headers.
# Each value is a list of candidate header names to search for (first match wins).
# None in `candidates` means "no direct column — leave blank".
DRIVER_MAP: dict[str, list[str]] = {
    "dcpi_5_adj":          ["dcpi_2007_2011"],       # 5-year average inflation
    "nom_rir_vol":         ["nom_rir_vol_2011"],
    "gdp_capita":          ["gdp_capita_2011"],
    "growth_vol":          ["growth_vol_2010_2011"],
    "macro_var":           ["ic_2011"],              # "investment climate" used as macro qualitative proxy
    "atf":                 ["atf_2011"],
    "dt":                  ["dt_2011"],
    "fdg_3yr":             ["fdg_2011"],             # approximation: use 2011 level (3yr avg not in raw)
    "cof":                 ["cof_2011"],
    "pr":                  ["pr_2011"],
    "rol":                 ["rol_2011"],
    "db":                  ["db_2011"],
    "sr":                  ["sr_2011"],
    "debt_service_ratio":  ["dsr_2011"],
}

# Target column (EIU rating) — search candidates across common Excel naming styles.
EIU_CANDIDATES = ["eiu_2011", "EIU_score", "EIU_2011", "eiu_score", "EIU"]


def _header_index(header: list[str | None], names: list[str]) -> int | None:
    lower = [str(h).strip().lower() if h is not None else "" for h in header]
    for n in names:
        needle = n.strip().lower()
        if needle in lower:
            return lower.index(needle)
    return None


def _extract_one_sheet(wb, sheet_name: str, segment: str, out_csv: Path) -> int:
    ws = wb[sheet_name]
    rows = list(ws.iter_rows(values_only=True))
    header = list(rows[0])

    iso_idx = _header_index(header, ["iso_code"])
    name_idx = _header_index(header, ["country"])
    eiu_idx = _header_index(header, EIU_CANDIDATES)

    driver_indices: dict[str, int | None] = {
        code: _header_index(header, cands) for code, cands in DRIVER_MAP.items()
    }

    out_rows = []
    for r in rows[1:]:
        iso = r[iso_idx] if iso_idx is not None else None
        name = r[name_idx] if name_idx is not None else None
        if not (iso and name):
            continue
        row: dict[str, object] = {
            "iso3": str(iso).strip(),
            "name": str(name).strip(),
            "segment": segment,
            "eiu_score": r[eiu_idx] if eiu_idx is not None else None,
        }
        for code, idx in driver_indices.items():
            row[code] = r[idx] if idx is not None else None
        out_rows.append(row)

    fieldnames = ["iso3", "name", "segment", "eiu_score"] + list(DRIVER_MAP.keys())
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in out_rows:
            w.writerow({k: ("" if row[k] is None else row[k]) for k in fieldnames})
    return len(out_rows)


def main() -> None:
    SEEDS_DIR.mkdir(parents=True, exist_ok=True)
    wb = load_workbook(XLSX, data_only=True)

    n_high = _extract_one_sheet(wb, "High_Raw", "HIGH", SEEDS_DIR / "training_high.csv")
    n_low = _extract_one_sheet(wb, "Low_Raw", "LOW", SEEDS_DIR / "training_low.csv")

    print(f"Wrote {n_high} HIGH training rows -> {SEEDS_DIR / 'training_high.csv'}")
    print(f"Wrote {n_low} LOW training rows -> {SEEDS_DIR / 'training_low.csv'}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the script**

```bash
cd "C:/Users/APR/OneDrive - Anchor Point Risk (Pty) Ltd/Desktop/VS_CODE_REPOSITORY/country-risk-model/"
./backend/.venv/Scripts/python.exe backend/scripts/extract_training_from_xlsx.py
```

Expected output: two `Wrote N ...` lines. N for HIGH should be ~90–100 rows, for LOW ~50–65 rows (approximate — the Excel has trailing blank rows).

- [ ] **Step 3: Sanity-check the CSVs**

```bash
wc -l supabase/seeds/training_high.csv
wc -l supabase/seeds/training_low.csv
head -3 supabase/seeds/training_high.csv
```

Expected: row counts match the script output (+ 1 for header); first 3 rows have 18 columns.

**Likely outcome on eiu_score:** If the `eiu_score` column is BLANK for every row, that means the Excel's "EIU rating" target column isn't one of the candidates above. Stop and report DONE_WITH_CONCERNS with the full column-header list from `High_Raw` — the user needs to map the correct target column name (likely one of the columns 50+ in the raw sheet). **Do NOT** proceed to Task 4 if `eiu_score` is empty; training will fail.

- [ ] **Step 4: Commit + push**

```bash
git add backend/scripts/extract_training_from_xlsx.py supabase/seeds/training_high.csv supabase/seeds/training_low.csv
git commit -m "feat(seeds): extract 2011 training data from Excel prototype"
git push
```

---

## Task 4: Domain types (dataclasses)

**Files:**
- Create: `backend/app/domain/__init__.py`
- Create: `backend/app/domain/types.py`
- Create: `backend/tests/domain/__init__.py`

- [ ] **Step 1: Create empty package markers**

```bash
cd "C:/Users/APR/OneDrive - Anchor Point Risk (Pty) Ltd/Desktop/VS_CODE_REPOSITORY/country-risk-model/"
mkdir -p backend/app/domain backend/tests/domain
touch backend/app/domain/__init__.py backend/tests/domain/__init__.py
```

- [ ] **Step 2: Create `backend/app/domain/types.py`**

```python
"""Pure-Python dataclasses shared across the domain layer.

No imports from FastAPI, Supabase, or any I/O library — these are the value objects
that travel between standardisation → buckets → training → scoring.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

Segment = Literal["HIGH", "LOW", "NODATA"]


@dataclass(frozen=True)
class StandardisationParam:
    variable_code: str
    mean: float
    std: float


@dataclass(frozen=True)
class Bucket:
    variable_code: str
    bucket_order: int
    lower_bound: float | None    # None = -infinity
    upper_bound: float | None    # None = +infinity
    score: float


@dataclass(frozen=True)
class ModelCoefficient:
    variable_code: str | None    # None when is_intercept=True
    coefficient: float
    is_intercept: bool = False


@dataclass(frozen=True)
class TrainedModel:
    segment: Segment
    coefficients: tuple[ModelCoefficient, ...]
    standardisation: tuple[StandardisationParam, ...]
    buckets: tuple[Bucket, ...]
    quant_variable_codes: tuple[str, ...]          # variables scored via buckets
    qual_variable_codes: tuple[str, ...]           # variables fed into Ridge
    training_data_hash: str
    fit_metrics: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class DriverInput:
    variable_code: str
    raw_value: float


@dataclass(frozen=True)
class DriverScore:
    variable_code: str
    raw_value: float
    standardised_value: float | None   # None for bucketed variables
    bucket_score: float | None         # None for Ridge variables
    contribution: float                # final numeric contribution to the score


@dataclass(frozen=True)
class ScoreResult:
    iso3: str
    segment: Segment
    final_score: float
    quant_score: float
    qual_score: float
    driver_scores: tuple[DriverScore, ...]
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/domain/__init__.py backend/app/domain/types.py backend/tests/domain/__init__.py
git commit -m "feat(domain): types module — TrainedModel, ScoreResult, DriverScore dataclasses"
git push
```

No test yet — pure dataclasses are trivially correct. Tests start in Task 5.

---

## Task 5: Standardisation (TDD)

**Files:**
- Create: `backend/tests/domain/test_standardisation.py`
- Create: `backend/app/domain/standardisation.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/domain/test_standardisation.py
from __future__ import annotations
import math
import pytest
import numpy as np

from app.domain.standardisation import fit_standardiser, standardise
from app.domain.types import StandardisationParam


def test_fit_standardiser_returns_mean_and_std_per_column():
    data = {
        "gdp_capita": [100.0, 200.0, 300.0],
        "inflation": [2.0, 4.0, 6.0],
    }
    params = fit_standardiser(data)
    by_code = {p.variable_code: p for p in params}

    assert math.isclose(by_code["gdp_capita"].mean, 200.0)
    assert math.isclose(by_code["gdp_capita"].std, np.std([100.0, 200.0, 300.0], ddof=0))
    assert math.isclose(by_code["inflation"].mean, 4.0)


def test_fit_standardiser_ignores_missing_values():
    data = {"gdp_capita": [100.0, float("nan"), 300.0]}
    params = fit_standardiser(data)
    by_code = {p.variable_code: p for p in params}
    assert math.isclose(by_code["gdp_capita"].mean, 200.0)


def test_fit_standardiser_raises_on_constant_column():
    data = {"gdp_capita": [5.0, 5.0, 5.0]}
    with pytest.raises(ValueError, match="zero variance"):
        fit_standardiser(data)


def test_standardise_applies_mean_and_std():
    param = StandardisationParam(variable_code="x", mean=10.0, std=2.0)
    assert math.isclose(standardise(param, 12.0), 1.0)
    assert math.isclose(standardise(param, 8.0), -1.0)
    assert math.isclose(standardise(param, 10.0), 0.0)


def test_standardise_with_zero_std_raises():
    param = StandardisationParam(variable_code="x", mean=10.0, std=0.0)
    with pytest.raises(ValueError, match="zero std"):
        standardise(param, 12.0)
```

- [ ] **Step 2: Run — confirm failure**

```bash
cd backend
source .venv/Scripts/activate
pytest tests/domain/test_standardisation.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.domain.standardisation'`.

- [ ] **Step 3: Implement `backend/app/domain/standardisation.py`**

```python
"""Per-variable mean/std computation and z-score application.

Pure-Python; no Supabase, no FastAPI. Operates on plain dicts / sequences so tests
don't need to construct heavier types.
"""
from __future__ import annotations
from collections.abc import Mapping, Sequence

import math
import numpy as np

from app.domain.types import StandardisationParam


def fit_standardiser(data: Mapping[str, Sequence[float]]) -> tuple[StandardisationParam, ...]:
    """Given {variable_code: [values]}, return population-std standardisation params.

    NaN values are ignored. Raises ValueError if any column has zero variance.
    """
    params: list[StandardisationParam] = []
    for code, values in data.items():
        arr = np.asarray(values, dtype=float)
        arr = arr[~np.isnan(arr)]
        if arr.size == 0:
            raise ValueError(f"variable {code}: no non-NaN values")
        mean = float(np.mean(arr))
        std = float(np.std(arr, ddof=0))
        if std == 0:
            raise ValueError(f"variable {code}: zero variance")
        params.append(StandardisationParam(variable_code=code, mean=mean, std=std))
    return tuple(params)


def standardise(param: StandardisationParam, value: float) -> float:
    """Return (value - mean) / std. Raises on zero std or NaN input."""
    if param.std == 0:
        raise ValueError(f"zero std for {param.variable_code}")
    if math.isnan(value):
        raise ValueError(f"NaN input for {param.variable_code}")
    return (value - param.mean) / param.std
```

- [ ] **Step 4: Run — should pass**

```bash
pytest tests/domain/test_standardisation.py -v
```

Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
cd ..
git add backend/app/domain/standardisation.py backend/tests/domain/test_standardisation.py
git commit -m "feat(domain): standardisation — fit + apply z-score (TDD)"
git push
```

---

## Task 6: Buckets (TDD)

**Files:**
- Create: `backend/tests/domain/test_buckets.py`
- Create: `backend/app/domain/buckets.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/domain/test_buckets.py
from __future__ import annotations
import math
import pytest

from app.domain.buckets import fit_quantile_buckets, bucket_score
from app.domain.types import Bucket


def test_fit_quantile_buckets_creates_equal_frequency_buckets():
    # 10 values, request 5 buckets → each bucket ~2 values
    values_by_code = {"gdp_capita": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]}
    targets_by_code = {"gdp_capita": [-2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0, 2.5]}
    buckets = fit_quantile_buckets(values_by_code, targets_by_code, n_buckets=5)
    gdp_buckets = sorted([b for b in buckets if b.variable_code == "gdp_capita"],
                         key=lambda b: b.bucket_order)
    assert len(gdp_buckets) == 5
    assert gdp_buckets[0].lower_bound is None   # extends to -inf
    assert gdp_buckets[-1].upper_bound is None  # extends to +inf
    # Scores increase with values (positive monotonic target)
    scores = [b.score for b in gdp_buckets]
    assert scores == sorted(scores)


def test_bucket_score_picks_the_right_bucket():
    buckets = (
        Bucket(variable_code="x", bucket_order=0, lower_bound=None,  upper_bound=10.0, score=-1.0),
        Bucket(variable_code="x", bucket_order=1, lower_bound=10.0, upper_bound=20.0,  score=0.0),
        Bucket(variable_code="x", bucket_order=2, lower_bound=20.0, upper_bound=None,  score=1.0),
    )
    assert bucket_score(buckets, "x", 5.0) == -1.0
    assert bucket_score(buckets, "x", 10.0) == 0.0       # lower boundary belongs to upper bucket
    assert bucket_score(buckets, "x", 15.0) == 0.0
    assert bucket_score(buckets, "x", 20.0) == 1.0
    assert bucket_score(buckets, "x", 100.0) == 1.0


def test_bucket_score_raises_when_variable_has_no_buckets():
    buckets = (
        Bucket(variable_code="y", bucket_order=0, lower_bound=None, upper_bound=None, score=0.0),
    )
    with pytest.raises(KeyError, match="no buckets"):
        bucket_score(buckets, "x", 5.0)


def test_fit_quantile_buckets_with_nan_inputs():
    values = {"gdp_capita": [10.0, 20.0, float("nan"), 40.0, 50.0]}
    targets = {"gdp_capita": [-1.0, 0.0, 1.0, 2.0, 3.0]}
    buckets = fit_quantile_buckets(values, targets, n_buckets=2)
    assert all(b.variable_code == "gdp_capita" for b in buckets)
    assert len(buckets) == 2
```

- [ ] **Step 2: Run — confirm failure**

```bash
cd backend
pytest tests/domain/test_buckets.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `backend/app/domain/buckets.py`**

```python
"""Quantile-based buckets: each variable is discretised into N buckets and each
bucket gets a score equal to the mean target value of its members."""
from __future__ import annotations
from collections.abc import Mapping, Sequence

import numpy as np

from app.domain.types import Bucket


def fit_quantile_buckets(
    values_by_code: Mapping[str, Sequence[float]],
    targets_by_code: Mapping[str, Sequence[float]],
    n_buckets: int,
) -> tuple[Bucket, ...]:
    """Fit equal-frequency buckets per variable and assign each bucket a score.

    For each variable:
    - rank its non-NaN values,
    - split into `n_buckets` equal-population buckets using quantile cut points,
    - bucket score = mean target value for the training rows in that bucket.

    Bucket 0 extends to -infinity on the left; bucket n-1 extends to +infinity on
    the right. Interior boundaries use the quantile cut points directly.
    """
    out: list[Bucket] = []
    for code, values in values_by_code.items():
        if code not in targets_by_code:
            raise ValueError(f"variable {code}: missing targets for bucket fit")
        x = np.asarray(values, dtype=float)
        y = np.asarray(targets_by_code[code], dtype=float)
        if x.shape != y.shape:
            raise ValueError(f"variable {code}: values and targets differ in length")

        mask = ~(np.isnan(x) | np.isnan(y))
        x, y = x[mask], y[mask]
        if x.size < n_buckets:
            raise ValueError(
                f"variable {code}: only {x.size} non-NaN rows, need >= {n_buckets}"
            )

        # Quantile cut points: n_buckets-1 interior thresholds.
        quantiles = np.linspace(0.0, 1.0, n_buckets + 1)[1:-1]
        cuts = np.quantile(x, quantiles, method="linear")

        # Assign each x to a bucket using np.digitize (right=False → left-inclusive on upper).
        # digitize returns values in [0, n_buckets]; 0 = left of all cuts.
        assignments = np.digitize(x, cuts, right=False)
        # Transform to bucket_order 0..n_buckets-1 directly.

        for order in range(n_buckets):
            lower = None if order == 0 else float(cuts[order - 1])
            upper = None if order == n_buckets - 1 else float(cuts[order])
            sel = y[assignments == order]
            score = float(np.mean(sel)) if sel.size else 0.0
            out.append(Bucket(
                variable_code=code,
                bucket_order=order,
                lower_bound=lower,
                upper_bound=upper,
                score=score,
            ))
    return tuple(out)


def bucket_score(buckets: Sequence[Bucket], variable_code: str, value: float) -> float:
    """Look up the bucket containing `value` and return its score.

    A value equal to a boundary belongs to the UPPER bucket (lower-inclusive).
    """
    for_var = [b for b in buckets if b.variable_code == variable_code]
    if not for_var:
        raise KeyError(f"no buckets for variable {variable_code}")

    for b in sorted(for_var, key=lambda x: x.bucket_order):
        lower = float("-inf") if b.lower_bound is None else b.lower_bound
        upper = float("inf") if b.upper_bound is None else b.upper_bound
        # lower-inclusive, upper-exclusive, except the highest bucket which is +inf on the right
        if lower <= value < upper:
            return b.score
        if upper == float("inf") and value >= lower:
            return b.score
    # Fallback: top bucket (numerical edge cases)
    return for_var[-1].score
```

- [ ] **Step 4: Run — should pass**

```bash
pytest tests/domain/test_buckets.py -v
```

Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
cd ..
git add backend/app/domain/buckets.py backend/tests/domain/test_buckets.py
git commit -m "feat(domain): quantile buckets with target-mean scores (TDD)"
git push
```

---

## Task 7: Training pipeline (TDD)

**Files:**
- Create: `backend/tests/domain/test_training.py`
- Create: `backend/app/domain/training.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/domain/test_training.py
from __future__ import annotations
import math
import numpy as np

from app.domain.training import train_model_for_segment
from app.domain.types import TrainedModel


def _synthetic_training_data(n: int = 100, seed: int = 42) -> dict[str, list[float]]:
    """Synthetic data where eiu_score = 3*gdp_capita_z + 2*pr + noise."""
    rng = np.random.default_rng(seed)
    gdp = rng.uniform(500, 50000, size=n).tolist()
    inflation = rng.uniform(0.5, 15.0, size=n).tolist()
    pr = rng.integers(1, 8, size=n).astype(float).tolist()
    rol = rng.uniform(-2, 2, size=n).tolist()
    target = (
        3.0 * np.array([(g - np.mean(gdp)) / np.std(gdp) for g in gdp])
        + 2.0 * np.array(pr)
        + rng.normal(0, 0.1, size=n)
    ).tolist()
    return {
        "eiu_score": target,
        "gdp_capita": gdp,
        "dcpi_5_adj": inflation,
        "pr": pr,
        "rol": rol,
    }


def test_train_model_returns_trained_model_with_all_components():
    data = _synthetic_training_data()
    quant_codes = ("gdp_capita", "dcpi_5_adj")
    qual_codes = ("pr", "rol")

    model = train_model_for_segment(
        segment="HIGH",
        rows=data,
        quant_variable_codes=quant_codes,
        qual_variable_codes=qual_codes,
        n_buckets=5,
        ridge_alpha=1.0,
    )

    assert isinstance(model, TrainedModel)
    assert model.segment == "HIGH"
    assert model.quant_variable_codes == quant_codes
    assert model.qual_variable_codes == qual_codes

    # Standardisation: one entry per quant variable.
    std_codes = {p.variable_code for p in model.standardisation}
    assert std_codes == set(quant_codes)

    # Buckets: n_buckets per quant variable.
    for code in quant_codes:
        for_code = [b for b in model.buckets if b.variable_code == code]
        assert len(for_code) == 5

    # Coefficients: one per qual variable + one intercept.
    intercepts = [c for c in model.coefficients if c.is_intercept]
    assert len(intercepts) == 1
    var_coefs = [c for c in model.coefficients if not c.is_intercept]
    assert {c.variable_code for c in var_coefs} == set(qual_codes)

    # Fit metrics include r2 + rmse.
    assert "r2" in model.fit_metrics
    assert "rmse" in model.fit_metrics

    # training_data_hash is a non-empty sha256 hex.
    assert len(model.training_data_hash) == 64


def test_train_model_reproducible_for_same_input():
    data = _synthetic_training_data()
    m1 = train_model_for_segment(
        "HIGH", data, ("gdp_capita",), ("pr",), n_buckets=3, ridge_alpha=1.0,
    )
    m2 = train_model_for_segment(
        "HIGH", data, ("gdp_capita",), ("pr",), n_buckets=3, ridge_alpha=1.0,
    )
    assert m1.training_data_hash == m2.training_data_hash
    assert {c.coefficient for c in m1.coefficients} == {c.coefficient for c in m2.coefficients}
```

- [ ] **Step 2: Run — confirm failure**

```bash
cd backend
pytest tests/domain/test_training.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `backend/app/domain/training.py`**

```python
"""Train a Ridge regression model for one HDI segment.

Flow:
  1. Drop rows with any NaN in the columns we care about.
  2. Fit standardisation params from quant variables (on training data, after drop).
  3. Fit quantile buckets for quant variables (scored by target mean per bucket).
  4. Fit a Ridge regression on qualitative variables, using `eiu_score` as target.
  5. Return a frozen TrainedModel.
"""
from __future__ import annotations
import hashlib
import json
from collections.abc import Mapping, Sequence

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_squared_error, r2_score

from app.domain.buckets import fit_quantile_buckets
from app.domain.standardisation import fit_standardiser
from app.domain.types import ModelCoefficient, TrainedModel


def _drop_rows_with_nan(
    rows: Mapping[str, Sequence[float]],
    required_codes: Sequence[str],
) -> dict[str, list[float]]:
    cols = {c: np.asarray(rows[c], dtype=float) for c in required_codes}
    n = next(iter(cols.values())).shape[0]
    mask = np.ones(n, dtype=bool)
    for arr in cols.values():
        mask &= ~np.isnan(arr)
    return {c: arr[mask].tolist() for c, arr in cols.items()}


def _hash_training_data(rows: Mapping[str, Sequence[float]]) -> str:
    # Stable JSON of sorted (code, [values]) pairs — same input, same hash.
    serialisable = {k: [None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)
                        for v in rows[k]] for k in sorted(rows)}
    payload = json.dumps(serialisable, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def train_model_for_segment(
    segment: str,
    rows: Mapping[str, Sequence[float]],
    quant_variable_codes: tuple[str, ...],
    qual_variable_codes: tuple[str, ...],
    n_buckets: int = 5,
    ridge_alpha: float = 1.0,
) -> TrainedModel:
    """Fit standardisation + buckets (quant) and Ridge (qual). Return a TrainedModel."""
    required = ("eiu_score",) + quant_variable_codes + qual_variable_codes
    missing = [c for c in required if c not in rows]
    if missing:
        raise ValueError(f"rows missing columns: {missing}")

    clean = _drop_rows_with_nan(rows, required)
    y = np.asarray(clean["eiu_score"], dtype=float)

    # --- Standardisation (quant variables only) ---
    quant_data = {c: clean[c] for c in quant_variable_codes}
    std_params = fit_standardiser(quant_data)

    # --- Buckets (quant variables only) ---
    targets_by_code = {c: clean["eiu_score"] for c in quant_variable_codes}
    buckets = fit_quantile_buckets(quant_data, targets_by_code, n_buckets=n_buckets)

    # --- Ridge regression (qual variables only) ---
    X = np.column_stack([clean[c] for c in qual_variable_codes]) if qual_variable_codes else np.zeros((len(y), 0))
    if X.shape[0] < X.shape[1] + 1:
        raise ValueError(f"not enough training rows ({X.shape[0]}) for {X.shape[1]} qual variables")
    model = Ridge(alpha=ridge_alpha, random_state=0)
    model.fit(X, y)
    y_pred = model.predict(X)

    coefs: list[ModelCoefficient] = [
        ModelCoefficient(variable_code=None, coefficient=float(model.intercept_), is_intercept=True)
    ]
    for code, coef in zip(qual_variable_codes, model.coef_, strict=True):
        coefs.append(ModelCoefficient(variable_code=code, coefficient=float(coef)))

    fit_metrics = {
        "r2": float(r2_score(y, y_pred)),
        "rmse": float(np.sqrt(mean_squared_error(y, y_pred))),
        "n_training_rows": float(len(y)),
    }

    return TrainedModel(
        segment=segment,  # type: ignore[arg-type]
        coefficients=tuple(coefs),
        standardisation=std_params,
        buckets=buckets,
        quant_variable_codes=quant_variable_codes,
        qual_variable_codes=qual_variable_codes,
        training_data_hash=_hash_training_data(clean),
        fit_metrics=fit_metrics,
    )
```

- [ ] **Step 4: Run — should pass**

```bash
pytest tests/domain/test_training.py -v
```

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
cd ..
git add backend/app/domain/training.py backend/tests/domain/test_training.py
git commit -m "feat(domain): train Ridge+buckets+standardisation for a segment (TDD)"
git push
```

---

## Task 8: Scoring pipeline (TDD)

**Files:**
- Create: `backend/tests/domain/test_scoring.py`
- Create: `backend/app/domain/scoring.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/domain/test_scoring.py
from __future__ import annotations
import math

from app.domain.scoring import score_country
from app.domain.types import (
    Bucket,
    DriverInput,
    ModelCoefficient,
    StandardisationParam,
    TrainedModel,
)


def _toy_model() -> TrainedModel:
    return TrainedModel(
        segment="HIGH",
        coefficients=(
            ModelCoefficient(variable_code=None, coefficient=50.0, is_intercept=True),
            ModelCoefficient(variable_code="pr", coefficient=5.0, is_intercept=False),
            ModelCoefficient(variable_code="rol", coefficient=-3.0, is_intercept=False),
        ),
        standardisation=(
            StandardisationParam(variable_code="gdp_capita", mean=10000.0, std=5000.0),
        ),
        buckets=(
            Bucket(variable_code="gdp_capita", bucket_order=0, lower_bound=None,  upper_bound=-1.0, score=-2.0),
            Bucket(variable_code="gdp_capita", bucket_order=1, lower_bound=-1.0,  upper_bound=1.0,  score=0.0),
            Bucket(variable_code="gdp_capita", bucket_order=2, lower_bound=1.0,   upper_bound=None, score=2.0),
        ),
        quant_variable_codes=("gdp_capita",),
        qual_variable_codes=("pr", "rol"),
        training_data_hash="deadbeef" * 8,
        fit_metrics={"r2": 0.5, "rmse": 10.0, "n_training_rows": 80.0},
    )


def test_score_country_combines_quant_and_qual():
    model = _toy_model()
    inputs = (
        DriverInput(variable_code="gdp_capita", raw_value=15000.0),  # z = 1.0 → bucket 2 → score 2.0
        DriverInput(variable_code="pr",         raw_value=5.0),
        DriverInput(variable_code="rol",        raw_value=1.0),
    )
    result = score_country(iso3="USA", model=model, inputs=inputs)

    # Quant = sum of bucket scores = 2.0
    assert math.isclose(result.quant_score, 2.0)
    # Qual = intercept + 5*5 + (-3)*1 = 50 + 25 - 3 = 72
    assert math.isclose(result.qual_score, 72.0)
    # Final = quant + qual (baseline combination; refine later if needed)
    assert math.isclose(result.final_score, 74.0)
    assert result.iso3 == "USA"
    assert result.segment == "HIGH"

    # Each input produces a driver-score with its contribution.
    by_code = {d.variable_code: d for d in result.driver_scores}
    assert math.isclose(by_code["gdp_capita"].bucket_score, 2.0)
    assert math.isclose(by_code["pr"].contribution, 25.0)
    assert math.isclose(by_code["rol"].contribution, -3.0)


def test_score_country_errors_on_missing_driver():
    import pytest

    model = _toy_model()
    inputs = (DriverInput(variable_code="gdp_capita", raw_value=15000.0),)  # missing pr, rol

    with pytest.raises(ValueError, match="missing driver"):
        score_country(iso3="USA", model=model, inputs=inputs)
```

- [ ] **Step 2: Run — confirm failure**

```bash
cd backend
pytest tests/domain/test_scoring.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `backend/app/domain/scoring.py`**

```python
"""Apply a TrainedModel to a country's current driver values → ScoreResult.

Quant variables: standardise → bucket → bucket score. Sum of bucket scores.
Qual variables: Ridge linear combination (intercept + sum(coef_i * x_i)).
Final score: quant_score + qual_score.  (Keep it simple; calibration plan later.)
"""
from __future__ import annotations
from collections.abc import Sequence

from app.domain.buckets import bucket_score
from app.domain.standardisation import standardise
from app.domain.types import (
    DriverInput,
    DriverScore,
    ScoreResult,
    TrainedModel,
)


def _find_standardisation(model: TrainedModel, code: str):
    for p in model.standardisation:
        if p.variable_code == code:
            return p
    raise KeyError(f"no standardisation for {code}")


def _find_intercept(model: TrainedModel) -> float:
    for c in model.coefficients:
        if c.is_intercept:
            return c.coefficient
    return 0.0


def _find_qual_coef(model: TrainedModel, code: str) -> float:
    for c in model.coefficients:
        if c.variable_code == code and not c.is_intercept:
            return c.coefficient
    raise KeyError(f"no coefficient for qual variable {code}")


def score_country(
    iso3: str,
    model: TrainedModel,
    inputs: Sequence[DriverInput],
) -> ScoreResult:
    required = set(model.quant_variable_codes) | set(model.qual_variable_codes)
    provided = {i.variable_code: i.raw_value for i in inputs}
    missing = required - provided.keys()
    if missing:
        raise ValueError(f"missing driver(s): {sorted(missing)}")

    driver_scores: list[DriverScore] = []
    quant_total = 0.0

    for code in model.quant_variable_codes:
        raw = provided[code]
        std_param = _find_standardisation(model, code)
        z = standardise(std_param, raw)
        score = bucket_score(model.buckets, code, z)
        driver_scores.append(DriverScore(
            variable_code=code,
            raw_value=raw,
            standardised_value=z,
            bucket_score=score,
            contribution=score,
        ))
        quant_total += score

    qual_total = _find_intercept(model)
    for code in model.qual_variable_codes:
        raw = provided[code]
        coef = _find_qual_coef(model, code)
        contribution = coef * raw
        qual_total += contribution
        driver_scores.append(DriverScore(
            variable_code=code,
            raw_value=raw,
            standardised_value=None,
            bucket_score=None,
            contribution=contribution,
        ))

    return ScoreResult(
        iso3=iso3,
        segment=model.segment,
        final_score=quant_total + qual_total,
        quant_score=quant_total,
        qual_score=qual_total,
        driver_scores=tuple(driver_scores),
    )
```

- [ ] **Step 4: Run — should pass**

```bash
pytest tests/domain/test_scoring.py -v
```

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
cd ..
git add backend/app/domain/scoring.py backend/tests/domain/test_scoring.py
git commit -m "feat(domain): score_country — combine bucket quant + Ridge qual (TDD)"
git push
```

---

## Task 9: Model version repository

**Files:**
- Create: `backend/app/repositories/model_version.py`
- Create: `backend/app/schemas/model.py`

- [ ] **Step 1: Create `backend/app/schemas/model.py`** (pydantic I/O; not used by domain)

```python
from __future__ import annotations
from uuid import UUID
from pydantic import BaseModel


class ModelVersionOut(BaseModel):
    id: UUID
    segment: str
    trained_at: str       # ISO 8601 from Supabase
    training_data_hash: str
    status: str
```

- [ ] **Step 2: Create `backend/app/repositories/model_version.py`**

```python
"""Persist / load TrainedModel via Supabase. Uses service_client (bypasses RLS).
Only called from the internal admin path."""
from __future__ import annotations
from uuid import UUID

from supabase import Client

from app.domain.types import (
    Bucket,
    ModelCoefficient,
    StandardisationParam,
    TrainedModel,
)


class ModelVersionRepository:
    def __init__(self, client: Client) -> None:
        self._client = client

    def save(self, trained: TrainedModel, training_notes: str | None = None) -> UUID:
        """Insert a new model_versions row + its coefficients/standardisation/buckets.
        Returns the new model_version_id. All or nothing — caller should wrap in a
        try/except if partial rollback matters (Supabase-py doesn't expose tx)."""
        inserted = self._client.table("model_versions").insert({
            "segment": trained.segment,
            "training_notes": training_notes,
            "training_data_hash": trained.training_data_hash,
            "fit_metrics_json": trained.fit_metrics,
            "status": "active",
        }).execute()
        version_id = inserted.data[0]["id"]

        # Coefficients (intercept + qual variables)
        coef_rows = [
            {
                "model_version_id": version_id,
                "variable_code": c.variable_code,
                "coefficient": c.coefficient,
                "is_intercept": c.is_intercept,
            }
            for c in trained.coefficients
        ]
        if coef_rows:
            self._client.table("model_coefficients").insert(coef_rows).execute()

        # Standardisation params
        std_rows = [
            {
                "model_version_id": version_id,
                "variable_code": p.variable_code,
                "mean": p.mean,
                "std": p.std,
            }
            for p in trained.standardisation
        ]
        if std_rows:
            self._client.table("model_standardisation").insert(std_rows).execute()

        # Buckets
        bucket_rows = [
            {
                "model_version_id": version_id,
                "variable_code": b.variable_code,
                "bucket_order": b.bucket_order,
                "lower_bound": b.lower_bound,
                "upper_bound": b.upper_bound,
                "score": b.score,
            }
            for b in trained.buckets
        ]
        if bucket_rows:
            self._client.table("model_buckets").insert(bucket_rows).execute()

        return UUID(version_id)

    def load(self, model_version_id: UUID) -> TrainedModel:
        mv = self._client.table("model_versions").select("*").eq("id", str(model_version_id)).single().execute()
        mv_row = mv.data

        coefs = self._client.table("model_coefficients").select("*").eq("model_version_id", str(model_version_id)).execute().data
        stds = self._client.table("model_standardisation").select("*").eq("model_version_id", str(model_version_id)).execute().data
        bkts = self._client.table("model_buckets").select("*").eq("model_version_id", str(model_version_id)).order("variable_code").order("bucket_order").execute().data

        qual_codes = tuple(c["variable_code"] for c in coefs if not c["is_intercept"])
        quant_codes = tuple(sorted({s["variable_code"] for s in stds}))

        return TrainedModel(
            segment=mv_row["segment"],
            coefficients=tuple(
                ModelCoefficient(
                    variable_code=c["variable_code"],
                    coefficient=float(c["coefficient"]),
                    is_intercept=c["is_intercept"],
                )
                for c in coefs
            ),
            standardisation=tuple(
                StandardisationParam(
                    variable_code=s["variable_code"],
                    mean=float(s["mean"]),
                    std=float(s["std"]),
                )
                for s in stds
            ),
            buckets=tuple(
                Bucket(
                    variable_code=b["variable_code"],
                    bucket_order=b["bucket_order"],
                    lower_bound=float(b["lower_bound"]) if b["lower_bound"] is not None else None,
                    upper_bound=float(b["upper_bound"]) if b["upper_bound"] is not None else None,
                    score=float(b["score"]),
                )
                for b in bkts
            ),
            quant_variable_codes=quant_codes,
            qual_variable_codes=qual_codes,
            training_data_hash=mv_row["training_data_hash"],
            fit_metrics=mv_row.get("fit_metrics_json") or {},
        )
```

- [ ] **Step 3: Commit (no unit test — pure DB plumbing; tested via Task 11 integration)**

```bash
git add backend/app/repositories/model_version.py backend/app/schemas/model.py
git commit -m "feat(backend): model version repository (save/load TrainedModel)"
git push
```

---

## Task 10: Baseline training script (CLI)

**Files:**
- Create: `backend/scripts/train_baseline.py`

- [ ] **Step 1: Create `backend/scripts/train_baseline.py`**

```python
"""Train the v1 baseline model for each segment using prototype training data,
then persist to the linked Supabase dev project.

Usage (from the repo root, with the backend venv active and .env populated):
  python backend/scripts/train_baseline.py

Writes one model_versions row per segment ('HIGH' and 'LOW') along with its
coefficients / standardisation / bucket rows. Prints a summary to stdout.
"""
from __future__ import annotations
import csv
from pathlib import Path

from app.core.supabase import service_client
from app.domain.training import train_model_for_segment
from app.repositories.model_version import ModelVersionRepository

REPO_ROOT = Path(__file__).resolve().parents[2]
SEEDS = REPO_ROOT / "supabase" / "seeds"

QUANT_CODES = (
    "dcpi_5_adj",
    "nom_rir_vol",
    "gdp_capita",
    "growth_vol",
    "dt",
    "fdg_3yr",
    "cof",
    "debt_service_ratio",
)

QUAL_CODES = (
    "macro_var",
    "atf",
    "pr",
    "rol",
    "db",
    "sr",
)


def _read_csv(path: Path) -> dict[str, list[float]]:
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError(f"no rows in {path}")

    cols_of_interest = ("eiu_score",) + QUANT_CODES + QUAL_CODES
    out: dict[str, list[float]] = {c: [] for c in cols_of_interest}
    for r in rows:
        for c in cols_of_interest:
            v = r.get(c, "").strip()
            out[c].append(float(v) if v else float("nan"))
    return out


def train_one_segment(segment: str, csv_path: Path, repo: ModelVersionRepository) -> None:
    print(f"[{segment}] loading training data from {csv_path.name}")
    data = _read_csv(csv_path)
    print(f"[{segment}]   {len(data['eiu_score'])} rows loaded")

    print(f"[{segment}] training Ridge + buckets + standardisation...")
    model = train_model_for_segment(
        segment=segment,
        rows=data,
        quant_variable_codes=QUANT_CODES,
        qual_variable_codes=QUAL_CODES,
        n_buckets=5,
        ridge_alpha=1.0,
    )
    print(f"[{segment}]   fit_metrics = {model.fit_metrics}")

    print(f"[{segment}] persisting to Supabase...")
    version_id = repo.save(model, training_notes=f"baseline v1 for {segment}")
    print(f"[{segment}]   model_version_id = {version_id}")


def main() -> None:
    client = service_client()
    repo = ModelVersionRepository(client)

    train_one_segment("HIGH", SEEDS / "training_high.csv", repo)
    train_one_segment("LOW", SEEDS / "training_low.csv", repo)
    print("Done.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit (run in Task 11 integration test, not here)**

```bash
git add backend/scripts/train_baseline.py
git commit -m "feat(scripts): train_baseline — CLI to train + persist v1 models per segment"
git push
```

---

## Task 11: Integration test — full pipeline on prototype data

**Files:**
- Create: `backend/tests/integration/__init__.py`
- Create: `backend/tests/integration/test_baseline_training.py`

- [ ] **Step 1: Create the package marker**

```bash
mkdir -p backend/tests/integration
touch backend/tests/integration/__init__.py
```

- [ ] **Step 2: Write the test**

```python
# backend/tests/integration/test_baseline_training.py
"""Full-pipeline integration test.

Marked @pytest.mark.integration so it's excluded by default. Requires:
  SUPABASE_URL_DEV, SUPABASE_ANON_KEY_DEV, SUPABASE_SERVICE_ROLE_KEY_DEV,
  SUPABASE_JWT_SECRET_DEV — same env var names used by Task 15 of Plan 1.

Training CSVs must exist at supabase/seeds/training_{high,low}.csv.
"""
from __future__ import annotations
import os
import csv
from pathlib import Path
import pytest

from app.domain.scoring import score_country
from app.domain.training import train_model_for_segment
from app.domain.types import DriverInput

REPO_ROOT = Path(__file__).resolve().parents[3]
SEEDS = REPO_ROOT / "supabase" / "seeds"

QUANT_CODES = (
    "dcpi_5_adj", "nom_rir_vol", "gdp_capita", "growth_vol",
    "dt", "fdg_3yr", "cof", "debt_service_ratio",
)
QUAL_CODES = ("macro_var", "atf", "pr", "rol", "db", "sr")


def _load_csv(path: Path) -> tuple[dict[str, list[float]], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        raw_rows = list(csv.DictReader(f))
    cols_of_interest = ("eiu_score",) + QUANT_CODES + QUAL_CODES
    training: dict[str, list[float]] = {c: [] for c in cols_of_interest}
    for r in raw_rows:
        for c in cols_of_interest:
            v = r.get(c, "").strip()
            training[c].append(float(v) if v else float("nan"))
    return training, raw_rows


@pytest.mark.integration
def test_train_high_segment_from_prototype():
    if not os.environ.get("SUPABASE_URL_DEV"):
        pytest.skip("integration test requires SUPABASE_URL_DEV etc. in env")

    csv_path = SEEDS / "training_high.csv"
    if not csv_path.exists():
        pytest.skip(f"training CSV missing: {csv_path} (run Task 3 script)")

    data, _ = _load_csv(csv_path)

    # Drop columns with fewer than 30 non-nan rows — too sparse to train on.
    # (If this skips all rows, the CSV extraction needs revisiting.)
    n = len(data["eiu_score"])
    assert n >= 30, f"only {n} rows in training CSV — CSV extraction looks broken"

    model = train_model_for_segment(
        segment="HIGH",
        rows=data,
        quant_variable_codes=QUANT_CODES,
        qual_variable_codes=QUAL_CODES,
        n_buckets=5,
        ridge_alpha=1.0,
    )

    # Sanity: at least one coefficient per qual variable, reasonable r2.
    qual_coefs = [c for c in model.coefficients if not c.is_intercept]
    assert len(qual_coefs) == len(QUAL_CODES)
    assert model.fit_metrics["r2"] > -1.0, "model is worse than predicting the mean"
    assert model.fit_metrics["n_training_rows"] >= 30


@pytest.mark.integration
def test_score_single_country_from_trained_model():
    """Train on the HIGH CSV and score one country (USA) from its own training row."""
    if not os.environ.get("SUPABASE_URL_DEV"):
        pytest.skip("integration test requires SUPABASE_URL_DEV etc. in env")
    csv_path = SEEDS / "training_high.csv"
    if not csv_path.exists():
        pytest.skip(f"training CSV missing: {csv_path}")

    data, raw_rows = _load_csv(csv_path)
    model = train_model_for_segment(
        segment="HIGH",
        rows=data,
        quant_variable_codes=QUANT_CODES,
        qual_variable_codes=QUAL_CODES,
        n_buckets=5,
        ridge_alpha=1.0,
    )

    # Pick the first row where all drivers are present.
    usable = None
    for row in raw_rows:
        if all(row.get(c, "").strip() for c in (QUANT_CODES + QUAL_CODES + ("iso3",))):
            usable = row
            break
    if not usable:
        pytest.skip("no training row has all driver values present (expected on prototype data)")

    inputs = tuple(
        DriverInput(variable_code=c, raw_value=float(usable[c]))
        for c in (QUANT_CODES + QUAL_CODES)
    )
    result = score_country(iso3=usable["iso3"], model=model, inputs=inputs)

    assert result.iso3 == usable["iso3"]
    assert result.segment == "HIGH"
    assert isinstance(result.final_score, float)
    # Score should fall within [-1e3, 1e3] — a safety bound that catches pathological models.
    assert -1000.0 <= result.final_score <= 1000.0
    assert len(result.driver_scores) == len(QUANT_CODES) + len(QUAL_CODES)
```

- [ ] **Step 3: Run unit tests — should still pass, integration skipped**

```bash
cd backend
source .venv/Scripts/activate
pytest -v
```

Expected: all non-integration tests pass (previous 8 + 4 new domain tests = 12+). Integration tests deselected.

- [ ] **Step 4: Commit + push**

```bash
cd ..
git add backend/tests/integration
git commit -m "test(integration): full pipeline — train + score on prototype data"
git push
```

---

## Task 12: Run the baseline training end-to-end (user step)

**Not a code task — the user runs the training script once to produce the v1 model versions in Supabase.**

- [ ] **Step 1: From the repo root, with .env populated:**

```bash
cd "C:/Users/APR/OneDrive - Anchor Point Risk (Pty) Ltd/Desktop/VS_CODE_REPOSITORY/country-risk-model/"
source backend/.venv/Scripts/activate
python backend/scripts/train_baseline.py
```

Expected output: two `[HIGH] ...` and two `[LOW] ...` blocks, each ending with a fresh UUID for `model_version_id`.

- [ ] **Step 2: Verify in Supabase Studio**

In SQL editor for the dev project, run:

```sql
SELECT segment, id, trained_at, fit_metrics_json, status
FROM model_versions
ORDER BY trained_at DESC;
```

Expected: two rows (one per segment), `status = 'active'`.

```sql
SELECT model_version_id, count(*) AS n_coefficients
FROM model_coefficients
GROUP BY model_version_id;
```

Expected: n_coefficients = 7 per version (1 intercept + 6 qual variables).

```sql
SELECT model_version_id, count(*) AS n_buckets
FROM model_buckets
GROUP BY model_version_id;
```

Expected: n_buckets = 40 per version (8 quant variables × 5 buckets).

If the counts are wrong, investigate why; don't proceed.

- [ ] **Step 3: No commit needed** (the script writes to the DB, not the repo). Notify the orchestrator when the two model version IDs are created.

---

## Task 13: Tag and close Plan 2

- [ ] **Step 1: Final unit test run**

```bash
cd backend
source .venv/Scripts/activate
pytest -v
```

Expected: all pass, 0 failures, 0 errors.

- [ ] **Step 2: Tag**

```bash
cd ..
git tag -a plan-2-scoring-engine -m "Plan 2 complete: pure-Python scoring engine + Ridge training + persistence"
git push --tags
```

- [ ] **Step 3: Verify tag on GitHub**

`gh release list` or just browse to https://github.com/henrye1/country-risk-model/tags — the new tag should appear.

---

## Validation Checklist (end-of-plan)

Tick these before declaring Plan 2 done:

- [ ] All new backend unit tests pass (`pytest -v` from `backend/`).
- [ ] Migration `20260419000004_model_versions.sql` applied to `country-risk-dev` and Studio shows all four tables with RLS enabled.
- [ ] `supabase/seeds/training_high.csv` and `supabase/seeds/training_low.csv` exist and have plausible row counts (High ~90, Low ~55) with `eiu_score` populated for most rows.
- [ ] `python backend/scripts/train_baseline.py` completes without errors and produces two rows in `model_versions`.
- [ ] Each model version has 7 coefficient rows (1 intercept + 6 qual variables) and 40 bucket rows (8 quant × 5).
- [ ] The integration test in Task 11 passes when env vars are set (`pytest -m integration` after exporting `SUPABASE_URL_DEV` etc).
- [ ] Tag `plan-2-scoring-engine` is pushed to GitHub.

When all ticked: ready for **Plan 3 — Data ingestion** (manual upload + World Bank / WGI connectors writing to `raw_observations`).
