"""Generate predicted-vs-target diagnostics for a trained model on its training data.

Produces CSV + XLSX byte payloads suitable for HTTP file responses.
Same logic as `scripts/model_diagnostics.py` but factored for reuse.
"""
from __future__ import annotations
from dataclasses import dataclass
from io import BytesIO, StringIO
from typing import Iterable

import csv as csv_mod

import numpy as np
from openpyxl import Workbook
from sklearn.metrics import mean_absolute_error, r2_score

from app.domain.scoring import score_country
from app.domain.types import DriverInput, TrainedModel


@dataclass
class DiagnosticRow:
    iso3: str
    name: str
    target: float
    predicted: float
    residual: float
    quant_score: float
    qual_score: float
    drivers: dict[str, dict[str, float | None]]  # {var_code: {raw, contribution}}


@dataclass
class DiagnosticSummary:
    n: int
    correlation: float
    r2: float
    mae: float
    target_mean: float
    target_std: float
    target_min: float
    target_max: float
    pred_mean: float
    pred_std: float
    pred_min: float
    pred_max: float


def _score_training_rows(
    model: TrainedModel,
    rows: Iterable[dict],
) -> list[DiagnosticRow]:
    """Score each training row against `model`. Skip rows with missing target/drivers."""
    out: list[DiagnosticRow] = []
    required = tuple(model.quant_variable_codes) + tuple(model.qual_variable_codes)
    for r in rows:
        iso3 = r.get("iso3", "").strip()
        name = r.get("name", "").strip()
        target_str = r.get("eiu_score", "").strip()
        if not iso3 or not target_str:
            continue
        target = float(target_str)
        drivers: dict[str, float] = {}
        missing = False
        for code in required:
            v = r.get(code, "").strip()
            if not v:
                missing = True
                break
            drivers[code] = float(v)
        if missing:
            continue

        inputs = tuple(DriverInput(variable_code=c, raw_value=drivers[c]) for c in required)
        result = score_country(iso3=iso3, model=model, inputs=inputs)

        driver_payload: dict[str, dict[str, float | None]] = {}
        for ds in result.driver_scores:
            driver_payload[ds.variable_code] = {
                "raw": ds.raw_value,
                "contribution": ds.contribution,
            }

        out.append(DiagnosticRow(
            iso3=iso3,
            name=name,
            target=target,
            predicted=result.final_score,
            residual=target - result.final_score,
            quant_score=result.quant_score,
            qual_score=result.qual_score,
            drivers=driver_payload,
        ))
    return out


def _summary(rows: list[DiagnosticRow]) -> DiagnosticSummary:
    if not rows:
        return DiagnosticSummary(0, float("nan"), float("nan"), float("nan"),
                                 float("nan"), float("nan"), float("nan"), float("nan"),
                                 float("nan"), float("nan"), float("nan"), float("nan"))
    targets = np.array([r.target for r in rows])
    preds = np.array([r.predicted for r in rows])
    return DiagnosticSummary(
        n=len(rows),
        correlation=float(np.corrcoef(targets, preds)[0, 1]) if len(targets) > 1 else float("nan"),
        r2=float(r2_score(targets, preds)) if len(targets) > 1 else float("nan"),
        mae=float(mean_absolute_error(targets, preds)),
        target_mean=float(targets.mean()),
        target_std=float(targets.std()),
        target_min=float(targets.min()),
        target_max=float(targets.max()),
        pred_mean=float(preds.mean()),
        pred_std=float(preds.std()),
        pred_min=float(preds.min()),
        pred_max=float(preds.max()),
    )


def _ordered_driver_codes(model: TrainedModel) -> list[str]:
    return list(model.quant_variable_codes) + list(model.qual_variable_codes)


def _row_to_flat(row: DiagnosticRow, driver_codes: list[str]) -> dict[str, object]:
    flat: dict[str, object] = {
        "iso3": row.iso3,
        "name": row.name,
        "target": row.target,
        "predicted": row.predicted,
        "residual": row.residual,
        "quant_score": row.quant_score,
        "qual_score": row.qual_score,
    }
    for code in driver_codes:
        d = row.drivers.get(code, {})
        flat[f"{code}_raw"] = d.get("raw")
        flat[f"{code}_contribution"] = d.get("contribution")
    return flat


def generate_csv(model: TrainedModel, training_rows: Iterable[dict]) -> bytes:
    rows = _score_training_rows(model, training_rows)
    driver_codes = _ordered_driver_codes(model)
    fieldnames = ["iso3", "name", "target", "predicted", "residual",
                  "quant_score", "qual_score"]
    for code in driver_codes:
        fieldnames += [f"{code}_raw", f"{code}_contribution"]

    buf = StringIO()
    w = csv_mod.DictWriter(buf, fieldnames=fieldnames)
    w.writeheader()
    for r in rows:
        w.writerow(_row_to_flat(r, driver_codes))
    return buf.getvalue().encode("utf-8")


def generate_xlsx(model: TrainedModel, training_rows: Iterable[dict]) -> bytes:
    rows = _score_training_rows(model, training_rows)
    summary = _summary(rows)
    driver_codes = _ordered_driver_codes(model)

    wb = Workbook()
    # Summary sheet
    s_ws = wb.active
    s_ws.title = "Summary"
    s_ws.append(["Metric", "Value"])
    for label, value in [
        ("segment", model.segment),
        ("quant_variables", ", ".join(model.quant_variable_codes)),
        ("qual_variables", ", ".join(model.qual_variable_codes)),
        ("n", summary.n),
        ("correlation", summary.correlation),
        ("r2", summary.r2),
        ("mae", summary.mae),
        ("target_mean", summary.target_mean),
        ("target_std", summary.target_std),
        ("target_min", summary.target_min),
        ("target_max", summary.target_max),
        ("pred_mean", summary.pred_mean),
        ("pred_std", summary.pred_std),
        ("pred_min", summary.pred_min),
        ("pred_max", summary.pred_max),
        ("final_intercept", model.final_intercept),
        ("final_w_quant", model.final_w_quant),
        ("final_w_qual", model.final_w_qual),
    ]:
        s_ws.append([label, value])

    # Rows sheet
    r_ws = wb.create_sheet("Rows")
    fieldnames = ["iso3", "name", "target", "predicted", "residual",
                  "quant_score", "qual_score"]
    for code in driver_codes:
        fieldnames += [f"{code}_raw", f"{code}_contribution"]
    r_ws.append(fieldnames)
    for r in rows:
        flat = _row_to_flat(r, driver_codes)
        r_ws.append([flat.get(k) for k in fieldnames])

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
