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
    assert -1000.0 <= result.final_score <= 1000.0
    assert len(result.driver_scores) == len(QUANT_CODES) + len(QUAL_CODES)
