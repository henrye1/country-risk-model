"""Segment assignment lookup from country_segments table."""
from __future__ import annotations
from supabase import Client


class SegmentRepository:
    def __init__(self, client: Client) -> None:
        self._client = client

    def segment_by_iso3_as_of(self, as_of_year: int) -> dict[str, str]:
        """For each country, return its segment as of the most recent as_of_year
        <= the given year. Countries with no matching row are omitted."""
        resp = (
            self._client.table("country_segments")
            .select("iso3, as_of_year, segment")
            .lte("as_of_year", as_of_year)
            .order("as_of_year", desc=True)
            .execute()
        )
        latest: dict[str, str] = {}
        for row in resp.data:
            # First occurrence of an iso3 in desc-year order = its latest valid segment.
            latest.setdefault(row["iso3"], row["segment"])
        return latest
