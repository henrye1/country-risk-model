# How the Python training code works

This document explains the scoring engine and training pipeline at the level of code, files, and data flow. Read this if you need to understand, modify, or extend how country scores get produced.

## Mental model in one paragraph

The engine takes a country's raw driver values (GDP per capita, Rule of Law score, etc.) and produces a single risk score. Drivers split into two groups: **quantitative** ones go through a *standardisation → bucket-lookup* path; **qualitative** ones go through a *Ridge regression*. Both produce sub-scores (`quant_score`, `qual_score`). A second-stage Ridge — the **blending Ridge** — combines those two sub-scores into the **final score** using weights and an intercept that were fitted on the same training data. Training fits all of this; scoring just applies it. The whole engine is pure Python with no FastAPI or Supabase imports — it can be unit-tested in milliseconds.

---

## Where the code lives

```
backend/app/
├── domain/                              ← pure-Python engine (framework-free)
│   ├── types.py                         ← TrainedModel, ScoreResult, dataclasses
│   ├── standardisation.py               ← fit + apply z-scores
│   ├── buckets.py                       ← fit quantile buckets + look up scores
│   ├── training.py                      ← train_model_for_segment() — the trainer
│   └── scoring.py                       ← score_country() — applies a TrainedModel
│
├── services/                            ← orchestration that uses the domain
│   ├── training.py                      ← load CSV → call trainer → persist via repo
│   └── training_diagnostics.py          ← predicted-vs-target CSV + XLSX generators
│
├── repositories/
│   └── model_version.py                 ← persist/load TrainedModel via Supabase
│
├── api/admin.py                         ← /admin/model-versions/* endpoints
└── schemas/model.py                     ← request/response Pydantic models

backend/scripts/
├── train_baseline.py                    ← CLI: trains both segments from CSVs
├── ingest_world_bank.py                 ← CLI: pulls WB data into raw_observations
├── run_snapshot.py                      ← CLI: create/compute/diff/publish snapshots
├── extract_training_from_xlsx.py        ← One-off: prototype Excel → training CSVs
└── model_diagnostics.py                 ← CLI: pred-vs-target CSV (same as the API)

supabase/
├── migrations/                          ← SQL — incl. model_versions + status enum + triggers
└── seeds/
    ├── training_high.csv                ← HIGH-segment 2011 training data (98 rows)
    └── training_low.csv                 ← LOW-segment 2011 training data (61 rows)
```

The hard rule: **`domain/` never imports from `services/`, `repositories/`, `api/`, or any DB/HTTP library.** That's why all the math is testable without booting Supabase.

---

## Data shapes

### Inputs

The trainer takes a `dict[str, list[float]]` — the same column-oriented shape that comes from a CSV:

```python
rows = {
    "eiu_score": [0.5, -0.2, 1.3, ...],   # the target variable
    "gdp_capita": [50000, 1200, ...],     # quant driver
    "cof": [4.2, 8.1, ...],
    "rol": [1.5, -0.3, ...],              # qual driver
    "pr": [1.2, 0.0, ...],
    ...
}
```

Each list is one observation (one country in 2011). The same index across all keys belongs to the same row. `nan` values are dropped row-wise before fitting.

### Outputs

`TrainedModel` (defined in [`backend/app/domain/types.py`](../backend/app/domain/types.py)) is the single value object that carries everything needed to score:

```python
@dataclass(frozen=True)
class TrainedModel:
    segment: Literal["HIGH", "LOW", "NODATA"]
    coefficients: tuple[ModelCoefficient, ...]      # qual-Ridge intercept + per-var coefs
    standardisation: tuple[StandardisationParam, ...]  # mean+std per quant variable
    buckets: tuple[Bucket, ...]                     # n_buckets per quant variable
    quant_variable_codes: tuple[str, ...]
    qual_variable_codes: tuple[str, ...]
    training_data_hash: str                          # sha256 — proves which rows trained this
    fit_metrics: dict[str, float]                    # r2, rmse, n_training_rows, etc.
    # The blending Ridge that combines (quant_score, qual_score) → final score:
    final_intercept: float | None
    final_w_quant: float | None
    final_w_qual: float | None
```

`ScoreResult` (also in `types.py`) is what `score_country()` returns:

```python
@dataclass(frozen=True)
class ScoreResult:
    iso3: str
    segment: Segment
    final_score: float
    quant_score: float
    qual_score: float
    driver_scores: tuple[DriverScore, ...]   # per-driver breakdown
```

---

## Training: step-by-step walk-through of `train_model_for_segment()`

File: [`backend/app/domain/training.py`](../backend/app/domain/training.py)

The function is called once per HDI segment (HIGH, LOW, optionally NODATA). Here's exactly what happens:

### Step 1 — Drop rows with any NaN

```python
clean = _drop_rows_with_nan(rows, required_codes=("eiu_score",) + quant + qual)
```

A row with even one missing column is unusable for supervised learning, so we drop it. This is row-wise, not column-wise — variables themselves are kept; only specific country-rows go away.

### Step 2 — Fit standardisation params (quant variables only)

```python
std_params = fit_standardiser({c: clean[c] for c in quant_variable_codes})
```

For each quantitative variable, compute the **population mean and std-dev** (`ddof=0`). Stored as one `StandardisationParam` per variable. These are needed at scoring time to z-score new observations.

Implementation: [`backend/app/domain/standardisation.py`](../backend/app/domain/standardisation.py).

### Step 3 — Fit quantile buckets (quant variables only)

```python
buckets = fit_quantile_buckets(quant_data, targets_by_code={...}, n_buckets=5)
```

For each quant variable:
1. Split its non-NaN values into `n_buckets` equal-frequency groups using `np.quantile`.
2. For each bucket, compute the **mean of the target (`eiu_score`) for the rows that fall in that bucket** — this becomes the `bucket.score`.
3. Bucket 0 extends to −∞ on the left; bucket N−1 extends to +∞ on the right.

End state: each quant variable has 5 buckets, each labelled with a score that approximates the average risk of countries in that bucket.

Implementation: [`backend/app/domain/buckets.py`](../backend/app/domain/buckets.py).

### Step 4 — Fit the qualitative-variable Ridge regression

```python
X = np.column_stack([clean[c] for c in qual_variable_codes])
model = Ridge(alpha=ridge_alpha, random_state=0)
model.fit(X, y)            # y = eiu_score
```

Standard scikit-learn `Ridge`. The output coefficients (intercept + one per qual variable) are stored as `ModelCoefficient` rows.

### Step 5 — Compute per-row `quant_score` and `qual_score` via `score_country` on a "preliminary" model

This is the key step that fixed the original calibration bug. Without it, `final = quant + qual` over-shoots the target by a factor of N (the number of buckets summed).

```python
prelim = TrainedModel(..., final_intercept=None, ...)        # no blending yet
quant_scores, qual_scores = [], []
for i in range(n_rows):
    inputs = tuple(DriverInput(c, clean[c][i]) for c in all_codes)
    res = score_country("_train", model=prelim, inputs=inputs)
    quant_scores.append(res.quant_score)
    qual_scores.append(res.qual_score)
```

We use the engine's own scoring path (Steps 1–3 above on the predict side) on every training row, capturing the two intermediate sub-scores.

### Step 6 — Fit the **blending Ridge**

```python
blend_X = np.column_stack([quant_scores, qual_scores])    # shape (n, 2)
blend = Ridge(alpha=ridge_alpha, random_state=0)
blend.fit(blend_X, y)
```

This second-stage Ridge learns: *given a country's quant-score and qual-score from the engine, what's the best linear combination to recover the target?*

The 3 numbers it produces are stashed into the returned `TrainedModel` as `final_intercept`, `final_w_quant`, `final_w_qual`.

### Step 7 — Compute fit metrics

```python
y_pred_final = blend.predict(blend_X)
fit_metrics = {
    "r2": r2_score(y, y_pred_final),                 # the headline R² (uses blending)
    "rmse": np.sqrt(mean_squared_error(y, y_pred_final)),
    "n_training_rows": float(n_rows),
    "r2_qual_ridge_only": r2_score(y, model.predict(X)),  # diagnostic: R² without blending
}
```

`fit_metrics["r2"]` is what the UI displays. `r2_qual_ridge_only` is kept around for debugging — it should always be ≤ the blended R² (the test `test_train_model_includes_blending_coefs` enforces this).

### Step 8 — Hash the training data + return the frozen `TrainedModel`

```python
training_data_hash = sha256(json.dumps(sorted training data))
return TrainedModel(...)
```

The hash is a regulatory artefact: anyone can recompute it from the same input rows and prove the model came from those exact rows.

---

## Scoring: step-by-step walk-through of `score_country()`

File: [`backend/app/domain/scoring.py`](../backend/app/domain/scoring.py).

Inputs: a `TrainedModel` and a tuple of `DriverInput(variable_code, raw_value)` — one per variable the model needs.

### Step 1 — Validate all required drivers are present

```python
required = set(model.quant_variable_codes) | set(model.qual_variable_codes)
missing = required - provided.keys()
if missing:
    raise ValueError(f"missing driver(s): {sorted(missing)}")
```

The snapshot service catches this and counts the country as `skipped_missing_data` — not an error.

### Step 2 — For each quant variable: standardise → bucket-score → accumulate

```python
quant_total = 0.0
for code in model.quant_variable_codes:
    raw = provided[code]
    z = standardise(_find_standardisation(model, code), raw)
    score = bucket_score(model.buckets, code, z)
    driver_scores.append(DriverScore(
        variable_code=code, raw_value=raw,
        standardised_value=z, bucket_score=score,
        contribution=score,
    ))
    quant_total += score
```

Each quant driver's bucket-score becomes its `contribution`.

### Step 3 — For each qual variable: linear contribution; sum + intercept

```python
qual_total = _find_intercept(model)             # qual Ridge intercept
for code in model.qual_variable_codes:
    raw = provided[code]
    coef = _find_qual_coef(model, code)
    contribution = coef * raw
    qual_total += contribution
    driver_scores.append(DriverScore(
        variable_code=code, raw_value=raw,
        standardised_value=None, bucket_score=None,
        contribution=contribution,
    ))
```

So `qual_total = ridge_intercept + Σ(coef × raw_value)` — exactly what `Ridge.predict()` would give.

### Step 4 — Apply the blending Ridge to compute `final_score`

```python
if model.final_intercept is not None:
    final_score = (
        model.final_intercept
        + model.final_w_quant * quant_total
        + model.final_w_qual * qual_total
    )
else:
    final_score = quant_total + qual_total       # back-compat fallback
```

Old models (trained before the blending fix) don't have the three blending fields, and we fall back to the additive formula. Any newly-trained model has them.

### Step 5 — Return `ScoreResult`

```python
return ScoreResult(
    iso3=iso3,
    segment=model.segment,
    final_score=final_score,
    quant_score=quant_total,
    qual_score=qual_total,
    driver_scores=tuple(driver_scores),
)
```

Used by:
- The snapshot service (writes to `country_scores` + `driver_scores` tables)
- The training pipeline itself (Step 5 of training)
- The diagnostics generator (predicted-vs-target tables)

---

## Persistence: how a `TrainedModel` round-trips through Supabase

File: [`backend/app/repositories/model_version.py`](../backend/app/repositories/model_version.py).

### Save (`repo.save(trained_model)`)

Writes 4 tables in order:

1. **`model_versions`** — one row with `segment`, `training_notes`, `training_data_hash`, `fit_metrics_json`, `status='pending_review'` (default).
2. **`model_coefficients`** — one row per `ModelCoefficient` (qual Ridge intercept + per-qual coef). Plus three special rows for the blending Ridge with sentinel codes:
   - `_FINAL_INTERCEPT` → `final_intercept`
   - `_FINAL_W_QUANT` → `final_w_quant`
   - `_FINAL_W_QUAL` → `final_w_qual`
3. **`model_standardisation`** — `(model_version_id, variable_code, mean, std)` per quant variable.
4. **`model_buckets`** — `(model_version_id, variable_code, bucket_order, lower_bound, upper_bound, score)` per bucket.

### Load (`repo.load(model_version_id)`)

Reverses the above. The blending coefs get split out of `model_coefficients` rows by their sentinel codes and reassembled into the `TrainedModel.final_*` fields.

---

## The training service (orchestration layer)

File: [`backend/app/services/training.py`](../backend/app/services/training.py).

This is the layer the API endpoint and the CLI both call. It does:

1. **Read the training CSV** for the given segment (`supabase/seeds/training_high.csv` or `_low.csv`).
2. Convert to the column-oriented `dict[str, list[float]]` the trainer expects.
3. Call `train_model_for_segment(...)`.
4. Call `repo.save(trained_model)` — which persists it as `pending_review`.
5. Return a `TrainResult` with the new ID and fit metrics.

### Two ways to invoke it

**A. The Admin UI**: `POST /admin/model-versions` (FastAPI route in `backend/app/api/admin.py`). Owner-only. Synchronous (~5 sec).

**B. The CLI**: `python backend/scripts/train_baseline.py [--quant ...] [--qual ...] [--notes ...]`. No auth. Used for bulk seeding. Lands as `pending_review` same as the API path.

---

## Model lifecycle: `pending_review → approved → active → retired`

Defined in [`supabase/migrations/20260420000004_model_status_lifecycle.sql`](../supabase/migrations/20260420000004_model_status_lifecycle.sql) and `_005_model_status_triggers.sql`.

### Allowed transitions (DB-enforced)

```
pending_review  ──approve──→  approved  ──activate──→  active  ──┐
       │                          │                              │
       └─────retire───────────────┴──────retire──────────────────┴→ retired
```

### Auto-retire trigger

When a model in segment `X` becomes `active`, a trigger automatically retires any *other* `active` model in segment `X`. This guarantees one active model per segment, which simplifies the snapshot compute logic (it just queries `WHERE status = 'active'`).

### Why two human gates (approve + activate)?

Per the spec, training a model and putting it into production scoring are intentionally distinct steps. An owner can:
- **Train** → see the diagnostics → decide whether the new model is reasonable
- **Approve** → mark it as having been reviewed
- **Activate** → cut over scoring to it (auto-retiring the predecessor)

Snapshot compute filters by `status='active'`, so `pending_review` and `approved` models are invisible to the scoring path until activation.

---

## Diagnostics: predicted vs target

File: [`backend/app/services/training_diagnostics.py`](../backend/app/services/training_diagnostics.py).

Same logic as the CLI [`backend/scripts/model_diagnostics.py`](../backend/scripts/model_diagnostics.py). The service version is what the Admin UI calls when you click "Download CSV / Excel" on a model detail page.

For each training-data row, it:
1. Calls `score_country()` with the model and the row's drivers
2. Captures `target` (actual `eiu_score`), `predicted` (`final_score`), `residual`, plus `quant_score`, `qual_score`, and per-driver `raw + contribution`

CSV is the row-by-row table. XLSX is the same table on a "Rows" sheet, plus a "Summary" sheet with overall stats (correlation, R², MAE, mean/std for both target and predicted, plus the blending intercept and weights).

Use this to **validate against the original Excel prototype**: you compare a few rows of `predicted` against the Excel's published scores and decide whether the new model is acceptable before approving.

---

## How to retrain (operationally)

### Via the Admin UI (recommended)

1. Sign in as an `internal_owner`
2. Navigate to **Models → Train new model**
3. Pick a segment (HIGH / LOW), tick variables, add a note, click **Train**
4. Wait 5–10 sec → land on the new model's detail page (status: `pending_review`)
5. Click **Download CSV** or **Excel**, validate against your prototype
6. Click **Approve** → status flips to `approved`
7. Click **Activate** → status flips to `active`; previous active model auto-retires
8. The next snapshot compute will use the new model

### Via the CLI (bulk / scripted)

```bash
cd backend
source .venv/Scripts/activate

# Train both segments at once with a custom variable set
python scripts/train_baseline.py \
    --quant gdp_capita,cof,debt_service_ratio \
    --qual rol,pr \
    --notes "monthly retrain — march 2026"

# Both new versions land as pending_review.
# Then approve + activate either via the UI or via SQL:
#   UPDATE model_versions SET status='approved' WHERE id='...';
#   UPDATE model_versions SET status='active'   WHERE id='...';
```

### Via the API directly (programmatic)

```bash
curl -X POST http://localhost:8000/admin/model-versions \
  -H "Authorization: Bearer $OWNER_JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "segment": "HIGH",
    "quant_codes": ["gdp_capita", "cof", "debt_service_ratio"],
    "qual_codes": ["rol", "pr"],
    "notes": "automated retrain"
  }'
```

Then `POST /admin/model-versions/{id}/approve` and `.../activate`.

---

## Tests

| Test | Where | What it covers |
|---|---|---|
| `test_standardisation.py` | unit | `fit_standardiser`, `standardise`, NaN handling, zero-variance error |
| `test_buckets.py` | unit | `fit_quantile_buckets`, boundary inclusion, NaN handling |
| `test_training.py` | unit | full trainer, reproducibility, blending coefs present + improving R² |
| `test_scoring.py` | unit | quant+qual aggregation, missing-driver error, **blending applied when present** |
| `test_baseline_training.py` | integration | full pipeline against real prototype CSV (skipped by default) |
| `test_admin_models.py` | integration | API endpoints for train/list/get/approve/activate/retire |

Run all unit tests:

```bash
cd backend
pytest -v                  # 54 unit tests pass; integration deselected
```

Integration tests require `SUPABASE_URL_DEV`, `SUPABASE_ANON_KEY_DEV`, `SUPABASE_SERVICE_ROLE_KEY_DEV`, `SUPABASE_JWT_SECRET_DEV` env vars set:

```bash
pytest -m integration -v
```

---

## Known limitations & recommended next moves

### Limitations

1. **Targets are 2011-only.** The `eiu_score` column in the training CSVs comes from the 2011 Excel snapshot. Multi-year training requires either historical EIU data or a different target source — not yet built.
2. **5 variables only.** Plan 3 ingests gdp_capita, cof, debt_service_ratio, rol, pr from World Bank. The original 14-variable prototype needs the EIU qualitative variables (atf, macro_var, sr, etc.) which require manual upload — not yet built.
3. **R² is low** (0.05–0.20 typical) because of the above two limits. The engine itself is correct; it's data-bound.
4. **No CV-based hyperparameter tuning.** `ridge_alpha` defaults to 1.0 with no grid search.
5. **Bucket scores are mean-target.** Could be median or other robust statistic; we picked mean to match the prototype.

### Recommended next moves to lift R²

- **Target-upload UI** — let an analyst upload a CSV of `(iso3, year, eiu_score)` so we can train on multi-year history.
- **Multi-year aggregate features** — compute 5-year inflation averages, GDP-growth volatility, etc. from `raw_observations` instead of using single-year values.
- **Cross-validation** — wrap the trainer in `RidgeCV` or `GridSearchCV` to tune `alpha` and bucket count.
- **Log-transform GDP** — GDP per capita is heavy-tailed; log-transforming usually helps linear models.
- **Add EIU qualitative inputs** — the prototype's full 14-variable set includes Access to Finance, Doing Business, Security Risk, etc. that require licensed/manual data.

Each would be a small focused micro-plan when you're ready.
