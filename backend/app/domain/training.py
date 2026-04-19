"""Train a Ridge regression model for one HDI segment.

Flow:
  1. Drop rows with any NaN in the columns we care about.
  2. Fit standardisation params from quant variables (on training data, after drop).
  3. Fit quantile buckets for quant variables (scored by target mean per bucket).
  4. Fit a Ridge regression on qualitative variables, using `eiu_score` as target.
  5. Return a frozen TrainedModel.
"""
from __future__ import annotations
import hashlib
import json
from collections.abc import Mapping, Sequence

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_squared_error, r2_score

from app.domain.buckets import fit_quantile_buckets
from app.domain.standardisation import fit_standardiser
from app.domain.types import ModelCoefficient, TrainedModel


def _drop_rows_with_nan(
    rows: Mapping[str, Sequence[float]],
    required_codes: Sequence[str],
) -> dict[str, list[float]]:
    cols = {c: np.asarray(rows[c], dtype=float) for c in required_codes}
    n = next(iter(cols.values())).shape[0]
    mask = np.ones(n, dtype=bool)
    for arr in cols.values():
        mask &= ~np.isnan(arr)
    return {c: arr[mask].tolist() for c, arr in cols.items()}


def _hash_training_data(rows: Mapping[str, Sequence[float]]) -> str:
    serialisable = {k: [None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)
                        for v in rows[k]] for k in sorted(rows)}
    payload = json.dumps(serialisable, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def train_model_for_segment(
    segment: str,
    rows: Mapping[str, Sequence[float]],
    quant_variable_codes: tuple[str, ...],
    qual_variable_codes: tuple[str, ...],
    n_buckets: int = 5,
    ridge_alpha: float = 1.0,
) -> TrainedModel:
    """Fit standardisation + buckets (quant) and Ridge (qual). Return a TrainedModel."""
    required = ("eiu_score",) + quant_variable_codes + qual_variable_codes
    missing = [c for c in required if c not in rows]
    if missing:
        raise ValueError(f"rows missing columns: {missing}")

    clean = _drop_rows_with_nan(rows, required)
    y = np.asarray(clean["eiu_score"], dtype=float)

    quant_data = {c: clean[c] for c in quant_variable_codes}
    std_params = fit_standardiser(quant_data)

    targets_by_code = {c: clean["eiu_score"] for c in quant_variable_codes}
    buckets = fit_quantile_buckets(quant_data, targets_by_code, n_buckets=n_buckets)

    X = np.column_stack([clean[c] for c in qual_variable_codes]) if qual_variable_codes else np.zeros((len(y), 0))
    if X.shape[0] < X.shape[1] + 1:
        raise ValueError(f"not enough training rows ({X.shape[0]}) for {X.shape[1]} qual variables")
    model = Ridge(alpha=ridge_alpha, random_state=0)
    model.fit(X, y)
    y_pred = model.predict(X)

    coefs: list[ModelCoefficient] = [
        ModelCoefficient(variable_code=None, coefficient=float(model.intercept_), is_intercept=True)
    ]
    for code, coef in zip(qual_variable_codes, model.coef_, strict=True):
        coefs.append(ModelCoefficient(variable_code=code, coefficient=float(coef)))

    fit_metrics = {
        "r2": float(r2_score(y, y_pred)),
        "rmse": float(np.sqrt(mean_squared_error(y, y_pred))),
        "n_training_rows": float(len(y)),
    }

    return TrainedModel(
        segment=segment,  # type: ignore[arg-type]
        coefficients=tuple(coefs),
        standardisation=std_params,
        buckets=buckets,
        quant_variable_codes=quant_variable_codes,
        qual_variable_codes=qual_variable_codes,
        training_data_hash=_hash_training_data(clean),
        fit_metrics=fit_metrics,
    )
