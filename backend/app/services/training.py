"""Training service: wraps domain.train_model_for_segment with CSV loading + persistence."""
from __future__ import annotations
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID

from app.domain.training import train_model_for_segment
from app.repositories.model_version import ModelVersionRepository

REPO_ROOT = Path(__file__).resolve().parents[3]
SEEDS = REPO_ROOT / "supabase" / "seeds"

Segment = Literal["HIGH", "LOW", "NODATA"]


@dataclass
class TrainResult:
    model_version_id: UUID
    segment: str
    fit_metrics: dict[str, float]
    n_training_rows: int


def _read_csv(
    path: Path,
    quant_codes: tuple[str, ...],
    qual_codes: tuple[str, ...],
) -> dict[str, list[float]]:
    rows = list(csv.DictReader(path.open("r", encoding="utf-8", newline="")))
    if not rows:
        raise ValueError(f"no rows in {path}")
    cols = ("eiu_score",) + quant_codes + qual_codes
    out: dict[str, list[float]] = {c: [] for c in cols}
    for r in rows:
        for c in cols:
            v = r.get(c, "").strip()
            out[c].append(float(v) if v else float("nan"))
    return out


def _csv_path_for(segment: Segment) -> Path:
    name = {"HIGH": "training_high.csv", "LOW": "training_low.csv"}.get(segment)
    if name is None:
        raise ValueError(f"no training CSV available for segment {segment}")
    return SEEDS / name


def train_segment(
    repo: ModelVersionRepository,
    segment: Segment,
    quant_codes: tuple[str, ...],
    qual_codes: tuple[str, ...],
    notes: str | None,
    n_buckets: int = 5,
    ridge_alpha: float = 1.0,
) -> TrainResult:
    csv_path = _csv_path_for(segment)
    data = _read_csv(csv_path, quant_codes, qual_codes)
    trained = train_model_for_segment(
        segment=segment,
        rows=data,
        quant_variable_codes=quant_codes,
        qual_variable_codes=qual_codes,
        n_buckets=n_buckets,
        ridge_alpha=ridge_alpha,
    )
    version_id = repo.save(trained, training_notes=notes)
    return TrainResult(
        model_version_id=version_id,
        segment=segment,
        fit_metrics=dict(trained.fit_metrics),
        n_training_rows=int(trained.fit_metrics.get("n_training_rows", 0)),
    )


def load_training_rows(segment: Segment) -> list[dict]:
    """Load the training CSV as a list of dicts (used by the diagnostics route)."""
    return list(csv.DictReader(_csv_path_for(segment).open("r", encoding="utf-8", newline="")))
