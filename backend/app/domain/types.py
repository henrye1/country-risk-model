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
    lower_bound: float | None
    upper_bound: float | None
    score: float


@dataclass(frozen=True)
class ModelCoefficient:
    variable_code: str | None
    coefficient: float
    is_intercept: bool = False


@dataclass(frozen=True)
class TrainedModel:
    segment: Segment
    coefficients: tuple[ModelCoefficient, ...]
    standardisation: tuple[StandardisationParam, ...]
    buckets: tuple[Bucket, ...]
    quant_variable_codes: tuple[str, ...]
    qual_variable_codes: tuple[str, ...]
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
    standardised_value: float | None
    bucket_score: float | None
    contribution: float


@dataclass(frozen=True)
class ScoreResult:
    iso3: str
    segment: Segment
    final_score: float
    quant_score: float
    qual_score: float
    driver_scores: tuple[DriverScore, ...]
