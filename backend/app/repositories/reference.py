from __future__ import annotations
from supabase import Client

from app.schemas.country import CountryOut
from app.schemas.variable import VariableOut


class ReferenceRepository:
    """Thin wrapper over Supabase client for reading reference tables."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def list_countries(self) -> list[CountryOut]:
        resp = self._client.table("countries").select("iso3, name, region").order("name").execute()
        return [CountryOut(**row) for row in resp.data]

    def list_variables(self) -> list[VariableOut]:
        resp = (
            self._client.table("variables")
            .select("code, name, category, direction, is_quantitative, description")
            .order("code")
            .execute()
        )
        return [VariableOut(**row) for row in resp.data]
