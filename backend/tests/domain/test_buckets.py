from __future__ import annotations
import math
import pytest

from app.domain.buckets import fit_quantile_buckets, bucket_score
from app.domain.types import Bucket


def test_fit_quantile_buckets_creates_equal_frequency_buckets():
    values_by_code = {"gdp_capita": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]}
    targets_by_code = {"gdp_capita": [-2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0, 2.5]}
    buckets = fit_quantile_buckets(values_by_code, targets_by_code, n_buckets=5)
    gdp_buckets = sorted([b for b in buckets if b.variable_code == "gdp_capita"],
                         key=lambda b: b.bucket_order)
    assert len(gdp_buckets) == 5
    assert gdp_buckets[0].lower_bound is None
    assert gdp_buckets[-1].upper_bound is None
    scores = [b.score for b in gdp_buckets]
    assert scores == sorted(scores)


def test_bucket_score_picks_the_right_bucket():
    buckets = (
        Bucket(variable_code="x", bucket_order=0, lower_bound=None,  upper_bound=10.0, score=-1.0),
        Bucket(variable_code="x", bucket_order=1, lower_bound=10.0, upper_bound=20.0,  score=0.0),
        Bucket(variable_code="x", bucket_order=2, lower_bound=20.0, upper_bound=None,  score=1.0),
    )
    assert bucket_score(buckets, "x", 5.0) == -1.0
    assert bucket_score(buckets, "x", 10.0) == 0.0
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
