from __future__ import annotations
from pydantic import BaseModel


class VariableOut(BaseModel):
    code: str
    name: str
    category: str
    direction: str
    is_quantitative: bool
    description: str | None = None
