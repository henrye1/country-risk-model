"""Ingestion service: orchestrate World Bank fetch → raw_observations insert."""
from __future__ import annotations
from typing import Protocol
from uuid import UUID

from app.ingestion.variable_sources import WORLD_BANK_SOURCES
from app.repositories.raw_observations import ObservationRow
from app.schemas.ingestion import IngestResultOut


class UnknownVariable(ValueError):
    """Raised when a requested variable_code has no WB mapping."""


class WBClientProtocol(Protocol):
    def fetch_indicator(
        self, indicator_id: str, start_year: int, end_year: int
    ) -> list[tuple[str, int, float | None]]: ...


class RawObsRepoProtocol(Protocol):
    def create_upload(self, source: str, file_name: str | None, notes: str | None, uploaded_by: UUID | None) -> UUID: ...
    def insert_observations(self, rows: list[ObservationRow], upload_id: UUID, ingested_by: UUID | None) -> int: ...
    def known_iso3_codes(self) -> set[str]: ...


class IngestionService:
    def __init__(self, wb_client: WBClientProtocol, repo: RawObsRepoProtocol) -> None:
        self._wb = wb_client
        self._repo = repo

    def ingest_world_bank(
        self,
        variable_codes: list[str],
        start_year: int,
        end_year: int,
        user_id: UUID | None,
        notes: str | None,
    ) -> IngestResultOut:
        """Fetch one WB indicator per variable across the year range, persist.

        If start_year == end_year it behaves like the old single-year path.
        """
        for code in variable_codes:
            if code not in WORLD_BANK_SOURCES:
                raise UnknownVariable(f"variable '{code}' has no World Bank mapping")

        first_source = WORLD_BANK_SOURCES[variable_codes[0]][0]
        upload_id = self._repo.create_upload(
            source=first_source,
            file_name=None,
            notes=notes,
            uploaded_by=user_id,
        )

        known_iso3 = self._repo.known_iso3_codes()

        rows: list[ObservationRow] = []
        skipped_unknown = 0
        skipped_null = 0
        warnings: list[str] = []

        for code in variable_codes:
            source_tag, indicator_id = WORLD_BANK_SOURCES[code]
            try:
                triples = self._wb.fetch_indicator(indicator_id, start_year, end_year)
            except Exception as exc:
                warnings.append(f"{code}: fetch failed — {exc}")
                continue

            for iso3, obs_year, value in triples:
                if iso3 not in known_iso3:
                    skipped_unknown += 1
                    continue
                if value is None:
                    skipped_null += 1
                    continue
                rows.append(ObservationRow(
                    iso3=iso3,
                    variable_code=code,
                    year=obs_year,
                    value=value,
                    source=source_tag,
                ))

        inserted = self._repo.insert_observations(rows, upload_id=upload_id, ingested_by=user_id)

        return IngestResultOut(
            upload_id=upload_id,
            source=first_source,
            year=end_year,  # response summary reports the latest year; full range is in `notes`
            variables_ingested=list(variable_codes),
            rows_inserted=inserted,
            rows_skipped_unknown_country=skipped_unknown,
            rows_skipped_null_value=skipped_null,
            warnings=warnings,
        )
