"""One-shot CLI to pull World Bank data into raw_observations.

Bypasses the FastAPI auth layer — calls the service directly with service_client().

Year argument accepts either a single year or a range:
    python backend/scripts/ingest_world_bank.py 2021
    python backend/scripts/ingest_world_bank.py 1996-2024
    python backend/scripts/ingest_world_bank.py 1996-2024 --variables rol,pr

If --variables is omitted, fetches all variables available via the API.
"""
from __future__ import annotations
import argparse
import json
import sys

from app.core.supabase import service_client
from app.ingestion.variable_sources import variables_available_via_api
from app.ingestion.world_bank import WorldBankClient
from app.repositories.raw_observations import RawObservationRepository
from app.services.ingestion import IngestionService


def _parse_years(arg: str) -> tuple[int, int]:
    """Accept '2021' or '1996-2024' → (start, end). End is inclusive."""
    if "-" in arg:
        s, e = arg.split("-", 1)
        start, end = int(s), int(e)
    else:
        start = end = int(arg)
    if end < start:
        raise argparse.ArgumentTypeError(f"end year ({end}) must be >= start year ({start})")
    return start, end


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("years", type=str, help="Single year (e.g. 2021) or range (e.g. 1996-2024)")
    p.add_argument(
        "--variables",
        type=str,
        default=None,
        help="Comma-separated variable codes (default: all available)",
    )
    p.add_argument("--notes", type=str, default="manual CLI ingest")
    args = p.parse_args()

    start_year, end_year = _parse_years(args.years)

    if args.variables:
        codes = [v.strip() for v in args.variables.split(",") if v.strip()]
    else:
        codes = list(variables_available_via_api())

    label = f"{start_year}" if start_year == end_year else f"{start_year}-{end_year}"
    print(f"Ingesting {codes} for years={label} ...")

    client = service_client()
    repo = RawObservationRepository(client)
    wb = WorldBankClient()
    service = IngestionService(wb_client=wb, repo=repo)

    result = service.ingest_world_bank(
        variable_codes=codes,
        start_year=start_year,
        end_year=end_year,
        user_id=None,
        notes=args.notes,
    )

    print(json.dumps(result.model_dump(mode="json"), indent=2))

    if result.warnings:
        print("\nWarnings:", file=sys.stderr)
        for w in result.warnings:
            print(f"  - {w}", file=sys.stderr)


if __name__ == "__main__":
    main()
