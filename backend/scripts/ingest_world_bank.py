"""One-shot CLI to pull a year of World Bank data into raw_observations.

Bypasses the FastAPI auth layer — calls the service directly with service_client().
Useful for bootstrap ingestion and for smoke-testing the full pipeline end-to-end.

Usage (from the repo root, with .env populated):
    python backend/scripts/ingest_world_bank.py 2021
    python backend/scripts/ingest_world_bank.py 2022 --variables gdp_capita,rol

If --variables is omitted, fetches all variables available via the API (see
`variable_sources.variables_available_via_api()`).

Prints the ingest result and exits 0 on success.
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


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("year", type=int, help="Year to ingest (e.g. 2021)")
    p.add_argument(
        "--variables",
        type=str,
        default=None,
        help="Comma-separated variable codes (default: all variables available via API)",
    )
    p.add_argument("--notes", type=str, default="manual CLI ingest")
    args = p.parse_args()

    if args.variables:
        codes = [v.strip() for v in args.variables.split(",") if v.strip()]
    else:
        codes = list(variables_available_via_api())

    print(f"Ingesting {codes} for year={args.year}...")

    client = service_client()
    repo = RawObservationRepository(client)
    wb = WorldBankClient()
    service = IngestionService(wb_client=wb, repo=repo)

    result = service.ingest_world_bank(
        variable_codes=codes,
        year=args.year,
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
