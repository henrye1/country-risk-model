"""Peer analysis: how does a country's drivers + predicted score compare to
the training-data cohort for its segment?

Per user spec:
- "Your value" for each driver = the country's raw value from the latest published
  country_score (i.e. the value that was used to score it).
- "Peer set" = all values for that driver in the training CSV (the portfolio the
  model was fit on).
- Predicted-score row uses final_score vs the training CSV's eiu_score column
  (the actual training target).
- The country itself is shown on the distribution as a marker; whether it was in
  the training CSV or not is irrelevant to the stats.
"""
from __future__ import annotations
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
SEEDS = REPO_ROOT / "supabase" / "seeds"

# Synthetic variable code for the predicted-score row.
PREDICTED_SCORE_CODE = "_PREDICTED_SCORE"


@dataclass(frozen=True)
class PeerStat:
    variable_code: str
    variable_name: str
    country_value: float | None
    n_peers: int
    peer_min: float
    peer_max: float
    peer_mean: float
    peer_std: float
    peer_p10: float
    peer_p25: float
    peer_median: float
    peer_p75: float
    peer_p90: float
    country_percentile: float | None  # 0-100, or None if country_value missing


def _csv_path_for(segment: str) -> Path | None:
    name = {"HIGH": "training_high.csv", "LOW": "training_low.csv"}.get(segment)
    return (SEEDS / name) if name else None


def _load_training_columns(
    segment: str,
    columns: Iterable[str],
) -> dict[str, list[float]]:
    """Read a training CSV and return {column: [values]} (NaN-filtered)."""
    path = _csv_path_for(segment)
    if path is None or not path.exists():
        return {c: [] for c in columns}

    out: dict[str, list[float]] = {c: [] for c in columns}
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            for c in columns:
                v = row.get(c, "").strip()
                if v:
                    try:
                        out[c].append(float(v))
                    except ValueError:
                        pass
    return out


def _compute_stat(
    variable_code: str,
    variable_name: str,
    country_value: float | None,
    peer_values: list[float],
) -> PeerStat:
    if not peer_values:
        return PeerStat(
            variable_code=variable_code,
            variable_name=variable_name,
            country_value=country_value,
            n_peers=0,
            peer_min=float("nan"), peer_max=float("nan"),
            peer_mean=float("nan"), peer_std=float("nan"),
            peer_p10=float("nan"), peer_p25=float("nan"),
            peer_median=float("nan"), peer_p75=float("nan"), peer_p90=float("nan"),
            country_percentile=None,
        )
    arr = np.asarray(peer_values, dtype=float)
    pcts = np.quantile(arr, [0.10, 0.25, 0.50, 0.75, 0.90])

    if country_value is None:
        country_percentile: float | None = None
    else:
        # Percentile rank: % of peers with values <= country's value.
        country_percentile = float((arr <= country_value).sum()) / float(arr.size) * 100.0

    return PeerStat(
        variable_code=variable_code,
        variable_name=variable_name,
        country_value=country_value,
        n_peers=int(arr.size),
        peer_min=float(arr.min()),
        peer_max=float(arr.max()),
        peer_mean=float(arr.mean()),
        peer_std=float(arr.std()),
        peer_p10=float(pcts[0]),
        peer_p25=float(pcts[1]),
        peer_median=float(pcts[2]),
        peer_p75=float(pcts[3]),
        peer_p90=float(pcts[4]),
        country_percentile=country_percentile,
    )


def build_peer_analysis(
    segment: str,
    driver_codes: list[str],
    driver_names: dict[str, str],
    country_driver_values: dict[str, float | None],
    country_final_score: float | None,
) -> list[PeerStat]:
    """Compute peer stats for each driver + a synthetic 'predicted score' row.

    Args:
      segment: "HIGH" or "LOW" (controls which training CSV is loaded).
      driver_codes: ordered list of driver variable codes to include.
      driver_names: {code: human-readable name} for response labels.
      country_driver_values: {code: this country's raw value} (None if missing).
      country_final_score: latest published final_score for this country (None if missing).
    """
    columns_to_load = list(driver_codes) + ["eiu_score"]
    cols = _load_training_columns(segment, columns_to_load)

    out: list[PeerStat] = []
    for code in driver_codes:
        out.append(_compute_stat(
            variable_code=code,
            variable_name=driver_names.get(code, code),
            country_value=country_driver_values.get(code),
            peer_values=cols.get(code, []),
        ))

    # Predicted score row: country's predicted final_score vs training eiu_score column.
    out.append(_compute_stat(
        variable_code=PREDICTED_SCORE_CODE,
        variable_name="Predicted score (vs training EIU)",
        country_value=country_final_score,
        peer_values=cols.get("eiu_score", []),
    ))
    return out
