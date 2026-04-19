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
