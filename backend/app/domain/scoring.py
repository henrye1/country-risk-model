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
