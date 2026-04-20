from __future__ import annotations
from uuid import UUID, uuid4

import pytest

from app.repositories.raw_observations import ObservationRow
from app.services.ingestion import (
    IngestionService,
    UnknownVariable,
)


class FakeWBClient:
    """Fake client keyed on (indicator_id, start_year, end_year)."""

    def __init__(self, payloads: dict[tuple[str, int, int], list[tuple[str, int, float | None]]]) -> None:
        self._payloads = payloads
        self.calls: list[tuple[str, int, int]] = []

    def fetch_indicator(
        self,
        indicator_id: str,
        start_year: int,
        end_year: int,
    ) -> list[tuple[str, int, float | None]]:
        self.calls.append((indicator_id, start_year, end_year))
        return self._payloads[(indicator_id, start_year, end_year)]


class FakeRepo:
    def __init__(self, known_iso3: set[str]) -> None:
        self._known = known_iso3
        self.uploads: list[dict] = []
        self.observations: list[ObservationRow] = []
        self.upload_id = uuid4()

    def create_upload(self, source, file_name, notes, uploaded_by):
        self.uploads.append({"source": source, "file_name": file_name, "notes": notes, "uploaded_by": uploaded_by})
        return self.upload_id

    def insert_observations(self, rows, upload_id, ingested_by):
        assert upload_id == self.upload_id
        self.observations.extend(rows)
        return len(rows)

    def known_iso3_codes(self) -> set[str]:
        return set(self._known)


def test_ingest_world_bank_maps_variables_and_inserts_rows():
    payloads = {
        ("NY.GDP.PCAP.CD", 2021, 2021): [
            ("USA", 2021, 70000.0),
            ("ZAF", 2021, 6000.0),
            ("ZZZ", 2021, 999.0),
        ],
        ("GOV_WGI_RL.EST", 2021, 2021): [
            ("USA", 2021, 1.5),
            ("ZAF", 2021, 0.2),
        ],
    }
    wb = FakeWBClient(payloads)
    repo = FakeRepo(known_iso3={"USA", "ZAF"})
    service = IngestionService(wb_client=wb, repo=repo)

    result = service.ingest_world_bank(
        variable_codes=["gdp_capita", "rol"],
        start_year=2021,
        end_year=2021,
        user_id=None,
        notes="test pull",
    )

    assert result.rows_inserted == 4
    assert result.rows_skipped_unknown_country == 1
    assert result.rows_skipped_null_value == 0
    assert sorted(result.variables_ingested) == ["gdp_capita", "rol"]
    assert result.upload_id == repo.upload_id

    by_var = {}
    for r in repo.observations:
        by_var.setdefault(r.variable_code, []).append(r)
    assert {r.iso3 for r in by_var["gdp_capita"]} == {"USA", "ZAF"}
    assert {r.iso3 for r in by_var["rol"]} == {"USA", "ZAF"}
    assert all(r.source == "WB" for r in by_var["gdp_capita"])
    assert all(r.source == "WGI" for r in by_var["rol"])
    assert all(r.year == 2021 for r in repo.observations)


def test_ingest_world_bank_spreads_year_across_observations():
    """When a range is fetched, each row gets its own year."""
    payloads = {
        ("NY.GDP.PCAP.CD", 2019, 2021): [
            ("USA", 2019, 65000.0),
            ("USA", 2020, 63000.0),
            ("USA", 2021, 70000.0),
            ("ZAF", 2021, 6000.0),
        ],
    }
    wb = FakeWBClient(payloads)
    repo = FakeRepo(known_iso3={"USA", "ZAF"})
    service = IngestionService(wb_client=wb, repo=repo)

    result = service.ingest_world_bank(
        variable_codes=["gdp_capita"],
        start_year=2019,
        end_year=2021,
        user_id=None,
        notes=None,
    )

    assert result.rows_inserted == 4
    years = sorted({r.year for r in repo.observations})
    assert years == [2019, 2020, 2021]


def test_ingest_world_bank_skips_null_values():
    payloads = {
        ("NY.GDP.PCAP.CD", 2021, 2021): [
            ("USA", 2021, None),
            ("ZAF", 2021, 6000.0),
        ],
    }
    wb = FakeWBClient(payloads)
    repo = FakeRepo(known_iso3={"USA", "ZAF"})
    service = IngestionService(wb_client=wb, repo=repo)

    result = service.ingest_world_bank(
        variable_codes=["gdp_capita"],
        start_year=2021,
        end_year=2021,
        user_id=None,
        notes=None,
    )

    assert result.rows_inserted == 1
    assert result.rows_skipped_null_value == 1
    assert len(repo.observations) == 1
    assert repo.observations[0].iso3 == "ZAF"


def test_ingest_world_bank_raises_on_unknown_variable():
    wb = FakeWBClient({})
    repo = FakeRepo(known_iso3=set())
    service = IngestionService(wb_client=wb, repo=repo)

    with pytest.raises(UnknownVariable, match="fake_var"):
        service.ingest_world_bank(
            variable_codes=["fake_var"],
            start_year=2021,
            end_year=2021,
            user_id=None,
            notes=None,
        )
