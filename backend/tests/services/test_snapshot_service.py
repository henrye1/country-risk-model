from __future__ import annotations
from datetime import date
from uuid import UUID, uuid4

import pytest

from app.domain.types import (
    Bucket,
    ModelCoefficient,
    StandardisationParam,
    TrainedModel,
)
from app.repositories.snapshot import (
    CountryScoreRow,
    DraftSnapshotCreate,
    DriverScoreRow,
)
from app.services.snapshot import (
    ComputeResult,
    MissingModelVersion,
    SnapshotService,
)


# --- Stubs ---------------------------------------------------------------

def _toy_model(segment: str = "HIGH") -> TrainedModel:
    return TrainedModel(
        segment=segment,  # type: ignore[arg-type]
        coefficients=(
            ModelCoefficient(variable_code=None, coefficient=0.0, is_intercept=True),
            ModelCoefficient(variable_code="pr", coefficient=1.0, is_intercept=False),
        ),
        standardisation=(
            StandardisationParam(variable_code="gdp_capita", mean=10000.0, std=5000.0),
        ),
        buckets=(
            Bucket(variable_code="gdp_capita", bucket_order=0, lower_bound=None, upper_bound=0.0, score=-1.0),
            Bucket(variable_code="gdp_capita", bucket_order=1, lower_bound=0.0, upper_bound=None, score=1.0),
        ),
        quant_variable_codes=("gdp_capita",),
        qual_variable_codes=("pr",),
        training_data_hash="abc" * 20,
        fit_metrics={"r2": 0.5},
    )


class FakeObservationsRepo:
    def __init__(self, observations: list[dict], known_iso3: set[str]) -> None:
        self._obs = observations
        self._iso3 = known_iso3

    def fetch_observations_up_to_year(self, max_year: int) -> list[dict]:
        return [o for o in self._obs if o["year"] <= max_year and o["value"] is not None]

    def known_iso3_codes(self) -> set[str]:
        return set(self._iso3)


class FakeModelRepo:
    def __init__(self, models: dict[UUID, TrainedModel]) -> None:
        self._models = models

    def load(self, model_version_id: UUID) -> TrainedModel:
        return self._models[model_version_id]


class FakeSnapshotRepo:
    def __init__(self) -> None:
        self.snapshot_id = uuid4()
        self.country_score_rows: list[CountryScoreRow] = []
        self.driver_score_rows: list[DriverScoreRow] = []
        self.created_draft: DraftSnapshotCreate | None = None
        self.wipes = 0

    def create_draft(self, draft: DraftSnapshotCreate) -> UUID:
        self.created_draft = draft
        return self.snapshot_id

    def wipe_draft_scores(self, snapshot_id: UUID) -> None:
        self.wipes += 1

    def insert_country_scores(self, snapshot_id: UUID, rows: list[CountryScoreRow]) -> int:
        assert snapshot_id == self.snapshot_id
        self.country_score_rows.extend(rows)
        return len(rows)

    def insert_driver_scores(self, snapshot_id: UUID, rows: list[DriverScoreRow]) -> int:
        assert snapshot_id == self.snapshot_id
        self.driver_score_rows.extend(rows)
        return len(rows)


class FakeSegmentRepo:
    """Returns {iso3: segment_code} for the most recent year <= year_of(as_of_date)."""

    def __init__(self, segments: dict[str, str]) -> None:
        self._segments = segments

    def segment_by_iso3_as_of(self, as_of_year: int) -> dict[str, str]:
        return dict(self._segments)


# --- Tests ---------------------------------------------------------------

def test_compute_produces_one_country_and_n_driver_rows_per_scorable_country():
    model_id_high = uuid4()
    obs_repo = FakeObservationsRepo(
        observations=[
            {"iso3": "USA", "variable_code": "gdp_capita", "year": 2022, "value": 70000.0, "ingested_at": "2026-04-01T00:00:00Z"},
            {"iso3": "USA", "variable_code": "pr", "year": 2022, "value": 1.0, "ingested_at": "2026-04-01T00:00:00Z"},
            {"iso3": "ZAF", "variable_code": "gdp_capita", "year": 2022, "value": 6000.0, "ingested_at": "2026-04-01T00:00:00Z"},
            {"iso3": "ZAF", "variable_code": "pr", "year": 2022, "value": 0.2, "ingested_at": "2026-04-01T00:00:00Z"},
        ],
        known_iso3={"USA", "ZAF"},
    )
    model_repo = FakeModelRepo({model_id_high: _toy_model("HIGH")})
    snapshot_repo = FakeSnapshotRepo()
    segment_repo = FakeSegmentRepo({"USA": "HIGH", "ZAF": "HIGH"})

    service = SnapshotService(
        obs_repo=obs_repo,
        model_repo=model_repo,
        snapshot_repo=snapshot_repo,
        segment_repo=segment_repo,
    )

    snapshot_id = service.create_draft(
        name="2026-Q2",
        as_of_date=date(2022, 12, 31),
        model_version_high=model_id_high,
        model_version_low=None,
        model_version_nodata=None,
        created_by=None,
    )
    result = service.compute(snapshot_id)

    assert isinstance(result, ComputeResult)
    assert result.countries_scored == 2
    assert result.countries_skipped_missing_data == 0
    assert result.countries_skipped_no_model == 0
    assert len(snapshot_repo.country_score_rows) == 2
    assert len(snapshot_repo.driver_score_rows) == 4  # 2 countries × 2 drivers
    assert snapshot_repo.wipes == 1


def test_compute_skips_country_with_missing_driver():
    model_id_high = uuid4()
    obs_repo = FakeObservationsRepo(
        observations=[
            {"iso3": "USA", "variable_code": "gdp_capita", "year": 2022, "value": 70000.0, "ingested_at": "2026-04-01T00:00:00Z"},
            # USA missing pr — should be skipped.
            {"iso3": "ZAF", "variable_code": "gdp_capita", "year": 2022, "value": 6000.0, "ingested_at": "2026-04-01T00:00:00Z"},
            {"iso3": "ZAF", "variable_code": "pr", "year": 2022, "value": 0.2, "ingested_at": "2026-04-01T00:00:00Z"},
        ],
        known_iso3={"USA", "ZAF"},
    )
    model_repo = FakeModelRepo({model_id_high: _toy_model("HIGH")})
    snapshot_repo = FakeSnapshotRepo()
    segment_repo = FakeSegmentRepo({"USA": "HIGH", "ZAF": "HIGH"})

    service = SnapshotService(
        obs_repo=obs_repo,
        model_repo=model_repo,
        snapshot_repo=snapshot_repo,
        segment_repo=segment_repo,
    )
    snapshot_id = service.create_draft(
        name="test",
        as_of_date=date(2022, 12, 31),
        model_version_high=model_id_high,
        model_version_low=None,
        model_version_nodata=None,
        created_by=None,
    )
    result = service.compute(snapshot_id)

    assert result.countries_scored == 1
    assert result.countries_skipped_missing_data == 1
    iso3s = {r.iso3 for r in snapshot_repo.country_score_rows}
    assert iso3s == {"ZAF"}


def test_compute_skips_country_with_no_model_for_its_segment():
    obs_repo = FakeObservationsRepo(observations=[], known_iso3={"USA"})
    model_repo = FakeModelRepo({})
    snapshot_repo = FakeSnapshotRepo()
    segment_repo = FakeSegmentRepo({"USA": "HIGH"})

    service = SnapshotService(
        obs_repo=obs_repo,
        model_repo=model_repo,
        snapshot_repo=snapshot_repo,
        segment_repo=segment_repo,
    )

    snapshot_id = service.create_draft(
        name="test",
        as_of_date=date(2022, 12, 31),
        model_version_high=None,   # no HIGH model
        model_version_low=None,
        model_version_nodata=None,
        created_by=None,
    )
    result = service.compute(snapshot_id)

    assert result.countries_scored == 0
    assert result.countries_skipped_no_model == 1


def test_compute_uses_latest_ingested_when_multiple_rows_for_same_year():
    model_id_high = uuid4()
    obs_repo = FakeObservationsRepo(
        observations=[
            # Two rows for USA gdp_capita in 2022 — latest ingested should win.
            {"iso3": "USA", "variable_code": "gdp_capita", "year": 2022, "value": 50000.0, "ingested_at": "2026-01-01T00:00:00Z"},
            {"iso3": "USA", "variable_code": "gdp_capita", "year": 2022, "value": 70000.0, "ingested_at": "2026-04-01T00:00:00Z"},
            {"iso3": "USA", "variable_code": "pr", "year": 2022, "value": 1.0, "ingested_at": "2026-04-01T00:00:00Z"},
        ],
        known_iso3={"USA"},
    )
    model_repo = FakeModelRepo({model_id_high: _toy_model("HIGH")})
    snapshot_repo = FakeSnapshotRepo()
    segment_repo = FakeSegmentRepo({"USA": "HIGH"})

    service = SnapshotService(
        obs_repo=obs_repo,
        model_repo=model_repo,
        snapshot_repo=snapshot_repo,
        segment_repo=segment_repo,
    )
    snapshot_id = service.create_draft(
        name="t", as_of_date=date(2022, 12, 31),
        model_version_high=model_id_high,
        model_version_low=None, model_version_nodata=None, created_by=None,
    )
    service.compute(snapshot_id)

    gdp_driver = next(r for r in snapshot_repo.driver_score_rows if r.variable_code == "gdp_capita")
    assert gdp_driver.raw_value == 70000.0
