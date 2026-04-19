from __future__ import annotations
from pydantic import BaseModel
from uuid import UUID


class CurrentUser(BaseModel):
    user_id: UUID
    email: str | None = None
    raw_jwt: str
