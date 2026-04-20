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

    std_codes = {p.variable_code for p in model.standardisation}
    assert std_codes == set(quant_codes)

    for code in quant_codes:
        for_code = [b for b in model.buckets if b.variable_code == code]
        assert len(for_code) == 5

    intercepts = [c for c in model.coefficients if c.is_intercept]
    assert len(intercepts) == 1
    var_coefs = [c for c in model.coefficients if not c.is_intercept]
    assert {c.variable_code for c in var_coefs} == set(qual_codes)

    assert "r2" in model.fit_metrics
    assert "rmse" in model.fit_metrics

    assert len(model.training_data_hash) == 64


def test_train_model_includes_blending_coefs():
    """The second-stage Ridge combining quant_score + qual_score must be fitted."""
    data = _synthetic_training_data()
    model = train_model_for_segment(
        "HIGH", data, ("gdp_capita",), ("pr", "rol"), n_buckets=3, ridge_alpha=1.0,
    )
    assert model.final_intercept is not None
    assert model.final_w_quant is not None
    assert model.final_w_qual is not None
    # The blending Ridge should never do worse than qual-Ridge alone.
    assert model.fit_metrics["r2"] >= model.fit_metrics["r2_qual_ridge_only"] - 1e-9


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
