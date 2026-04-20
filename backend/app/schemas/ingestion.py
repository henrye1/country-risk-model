from __future__ import annotations
from uuid import UUID
from pydantic import BaseModel, Field, model_validator


class WorldBankIngestRequest(BaseModel):
    """Ingest one or more variables for a year range (inclusive).

    Accept either `year` (single-year convenience) or `start_year`+`end_year`.
    When both are given, start_year/end_year win.
    """
    variables: list[str] = Field(min_length=1)
    year: int | None = Field(default=None, ge=1960, le=2100)
    start_year: int | None = Field(default=None, ge=1960, le=2100)
    end_year: int | None = Field(default=None, ge=1960, le=2100)
    notes: str | None = None

    @model_validator(mode="after")
    def _validate_years(self):
        has_range = self.start_year is not None and self.end_year is not None
        has_single = self.year is not None
        if not has_range and not has_single:
            raise ValueError("provide either 'year' or both 'start_year' and 'end_year'")
        if has_range and self.end_year < self.start_year:
            raise ValueError("end_year must be >= start_year")
        return self


class IngestResultOut(BaseModel):
    upload_id: UUID
    source: str
    year: int
    variables_ingested: list[str]
    rows_inserted: int
    rows_skipped_unknown_country: int
    rows_skipped_null_value: int
    warnings: list[str] = Field(default_factory=list)
