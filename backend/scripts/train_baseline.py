"""Train a Ridge model for each segment using prototype training data,
then persist to the linked Supabase dev project.

Usage (from the repo root, with the backend venv active and .env populated):
  python backend/scripts/train_baseline.py
  python backend/scripts/train_baseline.py \
      --quant gdp_capita,cof,debt_service_ratio \
      --qual rol,pr \
      --notes "subset model covering ingested data"

--quant / --qual accept comma-separated variable codes. Defaults train on the
full 14-variable baseline (matches the Excel prototype).

Writes one model_versions row per segment ('HIGH' and 'LOW') along with its
coefficients / standardisation / bucket rows. Prints a summary to stdout.
"""
from __future__ import annotations
import argparse
import csv
from pathlib import Path

from app.core.supabase import service_client
from app.domain.training import train_model_for_segment
from app.repositories.model_version import ModelVersionRepository

REPO_ROOT = Path(__file__).resolve().parents[2]
SEEDS = REPO_ROOT / "supabase" / "seeds"

DEFAULT_QUANT_CODES = (
    "dcpi_5_adj",
    "nom_rir_vol",
    "gdp_capita",
    "growth_vol",
    "dt",
    "fdg_3yr",
    "cof",
    "debt_service_ratio",
)

DEFAULT_QUAL_CODES = (
    "macro_var",
    "atf",
    "pr",
    "rol",
    "db",
    "sr",
)


def _read_csv(
    path: Path,
    quant_codes: tuple[str, ...],
    qual_codes: tuple[str, ...],
) -> dict[str, list[float]]:
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError(f"no rows in {path}")

    cols_of_interest = ("eiu_score",) + quant_codes + qual_codes
    out: dict[str, list[float]] = {c: [] for c in cols_of_interest}
    for r in rows:
        for c in cols_of_interest:
            v = r.get(c, "").strip()
            out[c].append(float(v) if v else float("nan"))
    return out


def train_one_segment(
    segment: str,
    csv_path: Path,
    repo: ModelVersionRepository,
    quant_codes: tuple[str, ...],
    qual_codes: tuple[str, ...],
    notes: str,
) -> None:
    print(f"[{segment}] loading training data from {csv_path.name}")
    data = _read_csv(csv_path, quant_codes, qual_codes)
    print(f"[{segment}]   {len(data['eiu_score'])} rows loaded")

    print(f"[{segment}] training Ridge + buckets + standardisation...")
    model = train_model_for_segment(
        segment=segment,
        rows=data,
        quant_variable_codes=quant_codes,
        qual_variable_codes=qual_codes,
        n_buckets=5,
        ridge_alpha=1.0,
    )
    print(f"[{segment}]   fit_metrics = {model.fit_metrics}")

    print(f"[{segment}] persisting to Supabase...")
    version_id = repo.save(model, training_notes=notes)
    print(f"[{segment}]   model_version_id = {version_id}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--quant",
        type=str,
        default=",".join(DEFAULT_QUANT_CODES),
        help="Comma-separated quantitative variable codes",
    )
    p.add_argument(
        "--qual",
        type=str,
        default=",".join(DEFAULT_QUAL_CODES),
        help="Comma-separated qualitative variable codes",
    )
    p.add_argument("--notes", type=str, default="baseline v1")
    args = p.parse_args()

    quant_codes = tuple(v.strip() for v in args.quant.split(",") if v.strip())
    qual_codes = tuple(v.strip() for v in args.qual.split(",") if v.strip())

    print(f"Quant variables ({len(quant_codes)}): {quant_codes}")
    print(f"Qual variables  ({len(qual_codes)}): {qual_codes}")
    print()

    client = service_client()
    repo = ModelVersionRepository(client)

    for segment, csv_name in [("HIGH", "training_high.csv"), ("LOW", "training_low.csv")]:
        train_one_segment(
            segment=segment,
            csv_path=SEEDS / csv_name,
            repo=repo,
            quant_codes=quant_codes,
            qual_codes=qual_codes,
            notes=f"{args.notes} — {segment}",
        )
    print("Done.")


if __name__ == "__main__":
    main()
