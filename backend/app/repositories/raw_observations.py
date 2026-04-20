"""Persist raw observations + data_uploads metadata via Supabase.

Called from the ingestion service (admin path). Uses whichever `supabase.Client`
is provided — typically `service_client()` since writes to these tables are
restricted to service_role by RLS.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from supabase import Client


@dataclass
class ObservationRow:
    iso3: str
    variable_code: str
    year: int
    value: float | None
    source: str


class RawObservationRepository:
    def __init__(self, client: Client) -> None:
        self._client = client

    def create_upload(
        self,
        source: str,
        file_name: str | None,
        notes: str | None,
        uploaded_by: UUID | None,
    ) -> UUID:
        """Create a data_uploads parent row. Returns its id.

        `row_count` is 0 here; it's patched after observations are inserted.
        """
        payload: dict[str, Any] = {
            "source": source,
            "file_name": file_name,
            "notes": notes,
            "row_count": 0,
        }
        if uploaded_by is not None:
            payload["uploaded_by"] = str(uploaded_by)
        resp = self._client.table("data_uploads").insert(payload).execute()
        return UUID(resp.data[0]["id"])

    def insert_observations(
        self,
        rows: list[ObservationRow],
        upload_id: UUID,
        ingested_by: UUID | None,
    ) -> int:
        """Batch-insert observations and update the upload's row_count. Returns n inserted."""
        if not rows:
            return 0
        payload_rows = [
            {
                "iso3": r.iso3,
                "variable_code": r.variable_code,
                "year": r.year,
                "value": r.value,
                "source": r.source,
                "upload_id": str(upload_id),
                "ingested_by": str(ingested_by) if ingested_by else None,
            }
            for r in rows
        ]
        CHUNK = 500
        inserted = 0
        for i in range(0, len(payload_rows), CHUNK):
            chunk = payload_rows[i : i + CHUNK]
            resp = self._client.table("raw_observations").insert(chunk).execute()
            inserted += len(resp.data)
        self._client.table("data_uploads").update({"row_count": inserted}).eq(
            "id", str(upload_id)
        ).execute()
        return inserted

    def known_iso3_codes(self) -> set[str]:
        """Return the iso3 codes present in the `countries` reference table.

        The ingestion service uses this to skip WB rows whose country isn't seeded
        (e.g. aggregate codes like 'WLD', 'AFE') — raw_observations has a FK on iso3.
        """
        resp = self._client.table("countries").select("iso3").execute()
        return {row["iso3"] for row in resp.data}

    def fetch_observations_up_to_year(self, max_year: int) -> list[dict]:
        """Return every raw observation whose year <= max_year and value is not null.

        Returned dicts contain iso3, variable_code, year, value, ingested_at.
        Callers reduce to "latest per (iso3, variable_code)" in Python.
        """
        # Supabase-py: paginate to get all rows (range fetch).
        all_rows: list[dict] = []
        page_size = 1000
        start = 0
        while True:
            resp = (
                self._client.table("raw_observations")
                .select("iso3, variable_code, year, value, ingested_at")
                .lte("year", max_year)
                .not_.is_("value", "null")
                .order("ingested_at", desc=True)
                .range(start, start + page_size - 1)
                .execute()
            )
            batch = resp.data
            if not batch:
                break
            all_rows.extend(batch)
            if len(batch) < page_size:
                break
            start += page_size
        return all_rows
