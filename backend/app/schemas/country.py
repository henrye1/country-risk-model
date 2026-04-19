from __future__ import annotations
from pydantic import BaseModel


class CountryOut(BaseModel):
    iso3: str
    name: str
    region: str | None = None
