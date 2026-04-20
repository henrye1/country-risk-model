"""Model diagnostics — compare predicted vs target on training data.

Usage:
    python backend/scripts/model_diagnostics.py                      # latest active model per segment
    python backend/scripts/model_diagnostics.py --model-id <uuid>    # specific model

Outputs:
    diagnostics_{SEGMENT}.csv at the repo root — one row per training country with:
        iso3, name, target, predicted, residual, quant_score, qual_score,
        <var>_raw and <var>_contribution for each driver.
    Terminal summary: n, correlation, R², MAE, target/pred distribution,
    top 10 over-predictions and top 10 under-predictions.
"""
from __future__ import annotations
import argparse
import csv
from pathlib import Path
from uuid import UUID

import numpy as np
from sklearn.metrics import mean_absolute_error, r2_score

from app.core.supabase import service_client
from app.domain.scoring import score_country
from app.domain.types import DriverInput
from app.repositories.model_version import ModelVersionRepository

REPO_ROOT = Path(__file__).resolve().parents[2]
SEEDS = REPO_ROOT / "supabase" / "seeds"


def _load_training_csv(csv_path: Path) -> list[dict]:
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _latest_models_per_segment() -> dict[str, dict]:
    client = service_client()
    resp = (
        client.table("model_versions")
        .select("id, segment, trained_at, fit_metrics_json, training_notes")
        .eq("status", "active")
        .order("trained_at", desc=True)
        .execute()
    )
    out: dict[str, dict] = {}
    for row in resp.data:
        out.setdefault(row["segment"], row)  # first = most recently trained
    return out


def _diagnose_segment(model_info: dict, repo: ModelVersionRepository, output_dir: Path) -> None:
    segment = model_info["segment"]
    model_id = UUID(model_info["id"])
    model = repo.load(model_id)

    csv_name = {"HIGH": "training_high.csv", "LOW": "training_low.csv"}.get(segment)
    if not csv_name:
        print(f"[{segment}] no training CSV available for this segment, skipping")
        return

    rows = _load_training_csv(SEEDS / csv_name)
    required_vars = tuple(model.quant_variable_codes) + tuple(model.qual_variable_codes)

    results: list[dict] = []
    skipped_no_target = 0
    skipped_missing_driver = 0

    for r in rows:
        iso3 = r["iso3"]
        name = r["name"]
        target_str = r.get("eiu_score", "").strip()
        if not target_str:
            skipped_no_target += 1
            continue
        target = float(target_str)

        drivers: dict[str, float] = {}
        missing: list[str] = []
        for var in required_vars:
            v = r.get(var, "").strip()
            if not v:
                missing.append(var)
            else:
                drivers[var] = float(v)
        if missing:
            skipped_missing_driver += 1
            continue

        inputs = tuple(DriverInput(variable_code=c, raw_value=drivers[c]) for c in required_vars)
        result = score_country(iso3=iso3, model=model, inputs=inputs)

        row_out = {
            "iso3": iso3,
            "name": name,
            "target": target,
            "predicted": result.final_score,
            "residual": target - result.final_score,
            "quant_score": result.quant_score,
            "qual_score": result.qual_score,
        }
        for ds in result.driver_scores:
            row_out[f"{ds.variable_code}_raw"] = ds.raw_value
            row_out[f"{ds.variable_code}_contribution"] = ds.contribution
        results.append(row_out)

    if not results:
        print(f"[{segment}] no scorable training rows "
              f"(skipped_no_target={skipped_no_target}, skipped_missing={skipped_missing_driver})")
        return

    # Write CSV with a stable priority column order.
    priority = ["iso3", "name", "target", "predicted", "residual", "quant_score", "qual_score"]
    all_keys: set[str] = set().union(*(r.keys() for r in results))
    fieldnames = priority + sorted(k for k in all_keys if k not in priority)
    csv_out = output_dir / f"diagnostics_{segment}.csv"
    with csv_out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(results)

    targets = np.array([r["target"] for r in results])
    preds = np.array([r["predicted"] for r in results])
    corr = float(np.corrcoef(targets, preds)[0, 1]) if len(targets) > 1 else float("nan")
    r2 = float(r2_score(targets, preds)) if len(targets) > 1 else float("nan")
    mae = float(mean_absolute_error(targets, preds))

    # Print summary
    print(f"\n=== Segment: {segment} ===")
    print(f"  model_version_id: {model_info['id']}")
    print(f"  trained_at:       {model_info.get('trained_at')}")
    print(f"  notes:            {model_info.get('training_notes')}")
    print(f"  quant vars:       {model.quant_variable_codes}")
    print(f"  qual  vars:       {model.qual_variable_codes}")
    print(f"  CSV written:      {csv_out}")
    print(f"  n scored:         {len(results)}")
    print(f"  skipped_no_target={skipped_no_target}  skipped_missing_driver={skipped_missing_driver}")
    print()
    print(f"  correlation:      {corr:+.3f}")
    print(f"  R² (in-sample):   {r2:+.3f}")
    print(f"  MAE:              {mae:.3f}")
    print(f"  target:  mean={targets.mean():+.3f}  std={targets.std():.3f}  range=[{targets.min():+.3f}, {targets.max():+.3f}]")
    print(f"  pred:    mean={preds.mean():+.3f}  std={preds.std():.3f}  range=[{preds.min():+.3f}, {preds.max():+.3f}]")

    # Top 10 over/under
    by_residual = sorted(results, key=lambda r: r["residual"])

    print(f"\n  [{segment}] Top 10 UNDER-predictions (model says low, target is high):")
    print(f"  {'ISO3':<5} {'target':>8} {'pred':>8} {'resid':>8}  name")
    for r in by_residual[-10:][::-1]:
        print(f"  {r['iso3']:<5} {r['target']:>+8.3f} {r['predicted']:>+8.3f} {r['residual']:>+8.3f}  {r['name']}")

    print(f"\n  [{segment}] Top 10 OVER-predictions (model says high, target is low):")
    print(f"  {'ISO3':<5} {'target':>8} {'pred':>8} {'resid':>8}  name")
    for r in by_residual[:10]:
        print(f"  {r['iso3']:<5} {r['target']:>+8.3f} {r['predicted']:>+8.3f} {r['residual']:>+8.3f}  {r['name']}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model-id", default=None, help="specific model_version_id; default: latest active per segment")
    args = p.parse_args()

    repo = ModelVersionRepository(service_client())
    output_dir = REPO_ROOT

    if args.model_id:
        row = (
            service_client()
            .table("model_versions")
            .select("id, segment, trained_at, training_notes")
            .eq("id", args.model_id)
            .single()
            .execute()
            .data
        )
        _diagnose_segment(row, repo, output_dir)
    else:
        for seg, info in _latest_models_per_segment().items():
            _diagnose_segment(info, repo, output_dir)


if __name__ == "__main__":
    main()
