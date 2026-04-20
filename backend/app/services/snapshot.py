"""Snapshot orchestration: create draft → compute scores → (later) publish."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol
from uuid import UUID

from app.domain.scoring import score_country
from app.domain.types import DriverInput, TrainedModel
from app.repositories.snapshot import (
    CountryScoreRow,
    DraftSnapshotCreate,
    DriverScoreRow,
)


class MissingModelVersion(ValueError):
    """Raised when a required model version is not available for a segment."""


class ObservationsRepoProtocol(Protocol):
    def fetch_observations_up_to_year(self, max_year: int) -> list[dict]: ...
    def known_iso3_codes(self) -> set[str]: ...


class ModelRepoProtocol(Protocol):
    def load(self, model_version_id: UUID) -> TrainedModel: ...


class SnapshotRepoProtocol(Protocol):
    def create_draft(self, draft: DraftSnapshotCreate) -> UUID: ...
    def wipe_draft_scores(self, snapshot_id: UUID) -> None: ...
    def insert_country_scores(self, snapshot_id: UUID, rows: list[CountryScoreRow]) -> int: ...
    def insert_driver_scores(self, snapshot_id: UUID, rows: list[DriverScoreRow]) -> int: ...
    def publish(self, snapshot_id: UUID, published_by: UUID | None, notes: str | None) -> dict: ...
    def archive(self, snapshot_id: UUID) -> dict: ...
    def list_snapshots(self, statuses: list[str] | None, limit: int) -> list[dict]: ...
    def latest_published_snapshot(self) -> dict | None: ...
    def country_scores_for(self, snapshot_id: UUID) -> list[dict]: ...


class SegmentRepoProtocol(Protocol):
    def segment_by_iso3_as_of(self, as_of_year: int) -> dict[str, str]: ...


@dataclass
class ComputeResult:
    snapshot_id: UUID
    countries_scored: int
    countries_skipped_missing_data: int
    countries_skipped_no_model: int
    countries_skipped_no_segment: int
    warnings: list[str] = field(default_factory=list)


class SnapshotService:
    def __init__(
        self,
        obs_repo: ObservationsRepoProtocol,
        model_repo: ModelRepoProtocol,
        snapshot_repo: SnapshotRepoProtocol,
        segment_repo: SegmentRepoProtocol,
    ) -> None:
        self._obs = obs_repo
        self._models = model_repo
        self._snapshots = snapshot_repo
        self._segments = segment_repo
        # Cache created-draft config so compute() can see it without a round trip.
        self._drafts: dict[UUID, DraftSnapshotCreate] = {}

    def create_draft(
        self,
        name: str,
        as_of_date: date,
        model_version_high: UUID | None,
        model_version_low: UUID | None,
        model_version_nodata: UUID | None,
        created_by: UUID | None,
    ) -> UUID:
        draft = DraftSnapshotCreate(
            name=name,
            as_of_date=as_of_date,
            model_version_high=model_version_high,
            model_version_low=model_version_low,
            model_version_nodata=model_version_nodata,
            created_by=created_by,
        )
        snapshot_id = self._snapshots.create_draft(draft)
        self._drafts[snapshot_id] = draft
        return snapshot_id

    def compute(self, snapshot_id: UUID) -> ComputeResult:
        draft = self._drafts.get(snapshot_id)
        if draft is None:
            raise KeyError(f"no draft cached for snapshot {snapshot_id}")

        as_of_year = draft.as_of_date.year

        # Load models per segment (only those the user requested).
        loaded_models: dict[str, TrainedModel] = {}
        for segment, version_id in [
            ("HIGH", draft.model_version_high),
            ("LOW", draft.model_version_low),
            ("NODATA", draft.model_version_nodata),
        ]:
            if version_id is not None:
                loaded_models[segment] = self._models.load(version_id)

        # Build a (iso3, variable_code) -> raw value lookup from latest observation.
        observations = self._obs.fetch_observations_up_to_year(as_of_year)
        latest: dict[tuple[str, str], dict] = {}
        for obs in observations:
            key = (obs["iso3"], obs["variable_code"])
            cur = latest.get(key)
            if cur is None:
                latest[key] = obs
                continue
            # Keep the one with the greatest year; break ties by ingested_at desc.
            if obs["year"] > cur["year"] or (
                obs["year"] == cur["year"] and obs["ingested_at"] > cur["ingested_at"]
            ):
                latest[key] = obs

        raw_by_country: dict[str, dict[str, float]] = {}
        for (iso3, code), obs in latest.items():
            raw_by_country.setdefault(iso3, {})[code] = float(obs["value"])

        segments_by_iso3 = self._segments.segment_by_iso3_as_of(as_of_year)
        known_iso3 = self._obs.known_iso3_codes()

        # Clear any prior draft rows (idempotent recompute).
        self._snapshots.wipe_draft_scores(snapshot_id)

        country_rows: list[CountryScoreRow] = []
        driver_rows: list[DriverScoreRow] = []
        scored = skipped_missing = skipped_no_model = skipped_no_segment = 0

        for iso3 in sorted(known_iso3):
            segment = segments_by_iso3.get(iso3)
            if segment is None:
                skipped_no_segment += 1
                continue

            model = loaded_models.get(segment)
            if model is None:
                skipped_no_model += 1
                continue

            drivers = raw_by_country.get(iso3, {})
            required = set(model.quant_variable_codes) | set(model.qual_variable_codes)
            missing = required - drivers.keys()
            if missing:
                skipped_missing += 1
                continue

            inputs = tuple(
                DriverInput(variable_code=code, raw_value=drivers[code])
                for code in required
            )
            result = score_country(iso3=iso3, model=model, inputs=inputs)

            country_rows.append(CountryScoreRow(
                iso3=iso3,
                segment=segment,
                final_score=result.final_score,
                quant_score=result.quant_score,
                qual_score=result.qual_score,
                bucket_band=None,  # banding deferred; placeholder for later plan
            ))
            for ds in result.driver_scores:
                driver_rows.append(DriverScoreRow(
                    iso3=iso3,
                    variable_code=ds.variable_code,
                    raw_value=ds.raw_value,
                    standardised_value=ds.standardised_value,
                    bucket_score=ds.bucket_score,
                    contribution=ds.contribution,
                ))
            scored += 1

        self._snapshots.insert_country_scores(snapshot_id, country_rows)
        self._snapshots.insert_driver_scores(snapshot_id, driver_rows)

        return ComputeResult(
            snapshot_id=snapshot_id,
            countries_scored=scored,
            countries_skipped_missing_data=skipped_missing,
            countries_skipped_no_model=skipped_no_model,
            countries_skipped_no_segment=skipped_no_segment,
        )

    def publish(self, snapshot_id: UUID, published_by: UUID | None, notes: str | None) -> dict:
        return self._snapshots.publish(snapshot_id, published_by=published_by, notes=notes)

    def archive(self, snapshot_id: UUID) -> dict:
        return self._snapshots.archive(snapshot_id)

    def list(self, statuses: list[str] | None = None, limit: int = 50) -> list[dict]:
        return self._snapshots.list_snapshots(statuses=statuses, limit=limit)

    def diff_against_latest_published(self, snapshot_id: UUID) -> dict:
        """Return diff rows comparing this snapshot's country_scores against
        the latest published snapshot. If none has been published yet,
        previous_snapshot_id is None and all deltas are None."""
        current_rows = self._snapshots.country_scores_for(snapshot_id)
        previous = self._snapshots.latest_published_snapshot()

        previous_id = previous["id"] if previous else None
        previous_rows = (
            self._snapshots.country_scores_for(UUID(previous["id"])) if previous else []
        )

        previous_by_iso3 = {r["iso3"]: r for r in previous_rows}

        diff_rows = []
        for cur in sorted(current_rows, key=lambda r: r["iso3"]):
            prev = previous_by_iso3.get(cur["iso3"])
            prev_score = float(prev["final_score"]) if prev else None
            new_score = float(cur["final_score"])
            delta = new_score - prev_score if prev_score is not None else None
            diff_rows.append({
                "iso3": cur["iso3"],
                "segment": cur["segment"],
                "new_score": new_score,
                "previous_score": prev_score,
                "delta": delta,
            })

        return {
            "snapshot_id": snapshot_id,
            "previous_snapshot_id": UUID(previous_id) if previous_id else None,
            "rows": diff_rows,
        }
