from __future__ import annotations
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field


class TrainModelRequest(BaseModel):
    segment: str  # "HIGH" | "LOW" | "NODATA"
    quant_codes: list[str] = Field(min_length=1)
    qual_codes: list[str] = Field(min_length=1)
    notes: str | None = None


class ModelVersionOut(BaseModel):
    id: UUID
    segment: str
    status: str
    trained_at: datetime
    training_notes: str | None
    training_data_hash: str
    fit_metrics_json: dict[str, float] = Field(default_factory=dict)


class TrainResultOut(BaseModel):
    model_version_id: UUID
    segment: str
    fit_metrics: dict[str, float]
    n_training_rows: int
