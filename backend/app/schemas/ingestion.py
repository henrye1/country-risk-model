from __future__ import annotations
from uuid import UUID
from pydantic import BaseModel, Field


class WorldBankIngestRequest(BaseModel):
    variables: list[str] = Field(min_length=1)
    year: int = Field(ge=1960, le=2100)
    notes: str | None = None


class IngestResultOut(BaseModel):
    upload_id: UUID
    source: str
    year: int
    variables_ingested: list[str]
    rows_inserted: int
    rows_skipped_unknown_country: int
    rows_skipped_null_value: int
    warnings: list[str] = Field(default_factory=list)
