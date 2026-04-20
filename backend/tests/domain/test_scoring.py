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

    assert math.isclose(result.quant_score, 2.0)
    assert math.isclose(result.qual_score, 72.0)
    assert math.isclose(result.final_score, 74.0)
    assert result.iso3 == "USA"
    assert result.segment == "HIGH"

    by_code = {d.variable_code: d for d in result.driver_scores}
    assert math.isclose(by_code["gdp_capita"].bucket_score, 2.0)
    assert math.isclose(by_code["pr"].contribution, 25.0)
    assert math.isclose(by_code["rol"].contribution, -3.0)


def test_score_country_errors_on_missing_driver():
    import pytest

    model = _toy_model()
    inputs = (DriverInput(variable_code="gdp_capita", raw_value=15000.0),)

    with pytest.raises(ValueError, match="missing driver"):
        score_country(iso3="USA", model=model, inputs=inputs)


def test_score_country_uses_blending_when_present():
    """When final_intercept/w_quant/w_qual are set, final_score should use the
    blending Ridge formula rather than the additive fallback."""
    from dataclasses import replace

    base = _toy_model()
    blended = replace(
        base,
        final_intercept=10.0,
        final_w_quant=0.5,
        final_w_qual=0.25,
    )
    inputs = (
        DriverInput(variable_code="gdp_capita", raw_value=15000.0),  # quant_total = 2.0
        DriverInput(variable_code="pr",         raw_value=5.0),      # qual contrib = 25
        DriverInput(variable_code="rol",        raw_value=1.0),      # qual contrib = -3
        # qual_total = 50 (intercept) + 25 - 3 = 72
    )
    result = score_country(iso3="USA", model=blended, inputs=inputs)

    # final = intercept + w_quant * quant + w_qual * qual = 10 + 0.5*2.0 + 0.25*72 = 29.0
    assert math.isclose(result.final_score, 29.0)
    # Quant + qual scores themselves are unchanged.
    assert math.isclose(result.quant_score, 2.0)
    assert math.isclose(result.qual_score, 72.0)
