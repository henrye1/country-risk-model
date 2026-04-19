"""Train the v1 baseline model for each segment using prototype training data,
then persist to the linked Supabase dev project.

Usage (from the repo root, with the backend venv active and .env populated):
  python backend/scripts/train_baseline.py

Writes one model_versions row per segment ('HIGH' and 'LOW') along with its
coefficients / standardisation / bucket rows. Prints a summary to stdout.
"""
from __future__ import annotations
import csv
from pathlib import Path

from app.core.supabase import service_client
from app.domain.training import train_model_for_segment
from app.repositories.model_version import ModelVersionRepository

REPO_ROOT = Path(__file__).resolve().parents[2]
SEEDS = REPO_ROOT / "supabase" / "seeds"

QUANT_CODES = (
    "dcpi_5_adj",
    "nom_rir_vol",
    "gdp_capita",
    "growth_vol",
    "dt",
    "fdg_3yr",
    "cof",
    "debt_service_ratio",
)

QUAL_CODES = (
    "macro_var",
    "atf",
    "pr",
    "rol",
    "db",
    "sr",
)


def _read_csv(path: Path) -> dict[str, list[float]]:
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError(f"no rows in {path}")

    cols_of_interest = ("eiu_score",) + QUANT_CODES + QUAL_CODES
    out: dict[str, list[float]] = {c: [] for c in cols_of_interest}
    for r in rows:
        for c in cols_of_interest:
            v = r.get(c, "").strip()
            out[c].append(float(v) if v else float("nan"))
    return out


def train_one_segment(segment: str, csv_path: Path, repo: ModelVersionRepository) -> None:
    print(f"[{segment}] loading training data from {csv_path.name}")
    data = _read_csv(csv_path)
    print(f"[{segment}]   {len(data['eiu_score'])} rows loaded")

    print(f"[{segment}] training Ridge + buckets + standardisation...")
    model = train_model_for_segment(
        segment=segment,
        rows=data,
        quant_variable_codes=QUANT_CODES,
        qual_variable_codes=QUAL_CODES,
        n_buckets=5,
        ridge_alpha=1.0,
    )
    print(f"[{segment}]   fit_metrics = {model.fit_metrics}")

    print(f"[{segment}] persisting to Supabase...")
    version_id = repo.save(model, training_notes=f"baseline v1 for {segment}")
    print(f"[{segment}]   model_version_id = {version_id}")


def main() -> None:
    client = service_client()
    repo = ModelVersionRepository(client)

    train_one_segment("HIGH", SEEDS / "training_high.csv", repo)
    train_one_segment("LOW", SEEDS / "training_low.csv", repo)
    print("Done.")


if __name__ == "__main__":
    main()
