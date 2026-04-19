from __future__ import annotations
from fastapi import APIRouter, Depends

from app.core.auth import get_current_user
from app.core.supabase import user_client
from app.repositories.reference import ReferenceRepository
from app.schemas.country import CountryOut
from app.schemas.user import CurrentUser
from app.schemas.variable import VariableOut

router = APIRouter(prefix="/v1", tags=["public"])


@router.get("/countries", response_model=list[CountryOut])
def list_countries(user: CurrentUser = Depends(get_current_user)) -> list[CountryOut]:
    repo = ReferenceRepository(user_client(user.raw_jwt))
    return repo.list_countries()


@router.get("/variables", response_model=list[VariableOut])
def list_variables(user: CurrentUser = Depends(get_current_user)) -> list[VariableOut]:
    repo = ReferenceRepository(user_client(user.raw_jwt))
    return repo.list_variables()
