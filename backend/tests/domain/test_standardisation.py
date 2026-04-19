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
