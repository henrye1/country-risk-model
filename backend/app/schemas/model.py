from __future__ import annotations
from uuid import UUID
from pydantic import BaseModel


class ModelVersionOut(BaseModel):
    id: UUID
    segment: str
    trained_at: str
    training_data_hash: str
    status: str
