from __future__ import annotations
from datetime import date, datetime
from uuid import UUID
from pydantic import BaseModel


class CountryOut(BaseModel):
    """Basic country reference data (pre-Plan-5 shape; still used by /v1/variables consumers)."""
    iso3: str
    name: str
    region: str | None = None


class CountrySummaryOut(BaseModel):
    """Country with latest published score (nullable if none available)."""
    iso3: str
    name: str
    region: str | None = None
    latest_final_score: float | None = None
    latest_bucket_band: str | None = None
    latest_segment: str | None = None
    latest_snapshot_id: UUID | None = None
    latest_as_of_date: date | None = None
    latest_published_at: datetime | None = None


class CountryScoreOut(BaseModel):
    """One published score for one country at a point in time.

    Includes the snapshot metadata and the model version IDs used — this is the
    audit-grade shape that PD/LGD consumers log alongside their own output.
    """
    iso3: str
    name: str
    segment: str
    final_score: float
    quant_score: float
    qual_score: float
    bucket_band: str | None
    snapshot_id: UUID
    snapshot_name: str
    as_of_date: date
    published_at: datetime
    model_version_high: UUID | None
    model_version_low: UUID | None
    model_version_nodata: UUID | None


class PeerStatOut(BaseModel):
    """Per-driver (or predicted-score) stats: where this country sits within
    the training cohort for its segment."""
    variable_code: str
    variable_name: str
    country_value: float | None
    n_peers: int
    peer_min: float
    peer_max: float
    peer_mean: float
    peer_std: float
    peer_p10: float
    peer_p25: float
    peer_median: float
    peer_p75: float
    peer_p90: float
    country_percentile: float | None


class PeerAnalysisOut(BaseModel):
    iso3: str
    name: str
    segment: str
    snapshot_id: UUID | None
    rows: list[PeerStatOut]
