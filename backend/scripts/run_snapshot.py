"""CLI to create + compute + (optionally) publish a draft snapshot.

Usage (from repo root, venv activated):
    python backend/scripts/run_snapshot.py create --name 2026-Q2 --as-of 2022-12-31
    python backend/scripts/run_snapshot.py compute <snapshot_id>
    python backend/scripts/run_snapshot.py diff    <snapshot_id>
    python backend/scripts/run_snapshot.py publish <snapshot_id>

Auto-picks the active model_version per segment (HIGH, LOW) from model_versions
unless overridden via --model-high / --model-low.
"""
from __future__ import annotations
import argparse
import json
from datetime import date
from uuid import UUID

from app.core.supabase import service_client
from app.repositories.model_version import ModelVersionRepository
from app.repositories.raw_observations import RawObservationRepository
from app.repositories.segment import SegmentRepository
from app.repositories.snapshot import DraftSnapshotCreate, SnapshotRepository
from app.services.snapshot import SnapshotService


def _service() -> SnapshotService:
    client = service_client()
    return SnapshotService(
        obs_repo=RawObservationRepository(client),
        model_repo=ModelVersionRepository(client),
        snapshot_repo=SnapshotRepository(client),
        segment_repo=SegmentRepository(client),
    )


def _latest_active_model_per_segment() -> dict[str, UUID]:
    client = service_client()
    resp = (
        client.table("model_versions")
        .select("id, segment, trained_at")
        .eq("status", "active")
        .order("trained_at", desc=True)
        .execute()
    )
    out: dict[str, UUID] = {}
    for row in resp.data:
        out.setdefault(row["segment"], UUID(row["id"]))
    return out


def cmd_create(args: argparse.Namespace) -> None:
    models = _latest_active_model_per_segment()
    mv_high = UUID(args.model_high) if args.model_high else models.get("HIGH")
    mv_low = UUID(args.model_low) if args.model_low else models.get("LOW")
    mv_nodata = UUID(args.model_nodata) if args.model_nodata else models.get("NODATA")

    service = _service()
    snapshot_id = service.create_draft(
        name=args.name,
        as_of_date=date.fromisoformat(args.as_of),
        model_version_high=mv_high,
        model_version_low=mv_low,
        model_version_nodata=mv_nodata,
        created_by=None,
    )
    print(f"Created draft snapshot: {snapshot_id}")
    print(f"  HIGH model:   {mv_high}")
    print(f"  LOW model:    {mv_low}")
    print(f"  NODATA model: {mv_nodata}")


def cmd_compute(args: argparse.Namespace) -> None:
    service = _service()
    row = SnapshotRepository(service_client()).get(UUID(args.snapshot_id))
    # Re-hydrate in-memory draft cache (service is stateless across CLI runs).
    service._drafts[UUID(args.snapshot_id)] = DraftSnapshotCreate(  # noqa: SLF001
        name=row["name"],
        as_of_date=date.fromisoformat(row["as_of_date"]),
        model_version_high=UUID(row["model_version_high"]) if row.get("model_version_high") else None,
        model_version_low=UUID(row["model_version_low"]) if row.get("model_version_low") else None,
        model_version_nodata=UUID(row["model_version_nodata"]) if row.get("model_version_nodata") else None,
        created_by=UUID(row["created_by"]) if row.get("created_by") else None,
    )
    result = service.compute(UUID(args.snapshot_id))
    print(json.dumps(result.__dict__, indent=2, default=str))


def cmd_diff(args: argparse.Namespace) -> None:
    service = _service()
    d = service.diff_against_latest_published(UUID(args.snapshot_id))
    rows = d["rows"]
    print(f"previous_snapshot_id: {d['previous_snapshot_id']}")
    print(f"rows: {len(rows)}")
    by_abs_delta = sorted(
        [r for r in rows if r["delta"] is not None],
        key=lambda r: abs(r["delta"]),
        reverse=True,
    )
    print("\nTop 10 movers (by |delta|):")
    print(f"  {'ISO3':<5} {'segment':<7} {'new':>10} {'prev':>10} {'delta':>10}")
    for r in by_abs_delta[:10]:
        print(f"  {r['iso3']:<5} {r['segment']:<7} {r['new_score']:>10.3f} {r['previous_score']:>10.3f} {r['delta']:>+10.3f}")


def cmd_publish(args: argparse.Namespace) -> None:
    service = _service()
    row = service.publish(UUID(args.snapshot_id), published_by=None, notes=args.notes)
    print(json.dumps(row, indent=2, default=str))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("create")
    pc.add_argument("--name", required=True)
    pc.add_argument("--as-of", required=True, help="YYYY-MM-DD")
    pc.add_argument("--model-high", default=None)
    pc.add_argument("--model-low", default=None)
    pc.add_argument("--model-nodata", default=None)
    pc.set_defaults(func=cmd_create)

    pco = sub.add_parser("compute")
    pco.add_argument("snapshot_id")
    pco.set_defaults(func=cmd_compute)

    pd = sub.add_parser("diff")
    pd.add_argument("snapshot_id")
    pd.set_defaults(func=cmd_diff)

    pp = sub.add_parser("publish")
    pp.add_argument("snapshot_id")
    pp.add_argument("--notes", default=None)
    pp.set_defaults(func=cmd_publish)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
