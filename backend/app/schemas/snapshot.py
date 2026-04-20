from __future__ import annotations
from datetime import date, datetime
from uuid import UUID
from pydantic import BaseModel, Field


class CreateSnapshotRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    as_of_date: date
    model_version_high: UUID | None = None
    model_version_low: UUID | None = None
    model_version_nodata: UUID | None = None


class ComputeSummaryOut(BaseModel):
    snapshot_id: UUID
    countries_scored: int
    countries_skipped_missing_data: int
    countries_skipped_no_model: int
    countries_skipped_no_segment: int
    warnings: list[str] = Field(default_factory=list)


class SnapshotOut(BaseModel):
    id: UUID
    name: str
    as_of_date: date
    status: str
    model_version_high: UUID | None
    model_version_low: UUID | None
    model_version_nodata: UUID | None
    created_by: UUID | None
    created_at: datetime
    published_by: UUID | None = None
    published_at: datetime | None = None
    published_notes: str | None = None


class PublishRequest(BaseModel):
    notes: str | None = None


class DiffRowOut(BaseModel):
    iso3: str
    segment: str
    new_score: float | None
    previous_score: float | None
    delta: float | None


class DiffOut(BaseModel):
    snapshot_id: UUID
    previous_snapshot_id: UUID | None
    rows: list[DiffRowOut]


class PublishedSnapshotOut(BaseModel):
    id: UUID
    name: str
    as_of_date: date
    status: str
    model_version_high: UUID | None
    model_version_low: UUID | None
    model_version_nodata: UUID | None
    published_at: datetime
    published_notes: str | None = None


class HistoryPointOut(BaseModel):
    snapshot_id: UUID
    snapshot_name: str
    as_of_date: date
    published_at: datetime
    segment: str
    final_score: float
    quant_score: float
    qual_score: float
    bucket_band: str | None


class DriverBreakdownOut(BaseModel):
    variable_code: str
    variable_name: str
    category: str
    direction: str
    is_quantitative: bool
    raw_value: float | None
    standardised_value: float | None
    bucket_score: float | None
    contribution: float
