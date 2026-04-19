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

        quantiles = np.linspace(0.0, 1.0, n_buckets + 1)[1:-1]
        cuts = np.quantile(x, quantiles, method="linear")

        assignments = np.digitize(x, cuts, right=False)

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
        if lower <= value < upper:
            return b.score
        if upper == float("inf") and value >= lower:
            return b.score
    return for_var[-1].score
