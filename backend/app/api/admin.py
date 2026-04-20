"""Admin API router — internal organisation members only."""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import get_current_user
from app.core.supabase import service_client
from app.ingestion.world_bank import WorldBankClient
from app.repositories.raw_observations import RawObservationRepository
from app.schemas.ingestion import IngestResultOut, WorldBankIngestRequest
from app.schemas.user import CurrentUser
from app.services.ingestion import IngestionService, UnknownVariable


router = APIRouter(prefix="/admin", tags=["admin"])


def _require_internal(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Role gate: the caller must belong to an organisation with status='internal'.
    We determine this by asking the service_client to read the caller's membership
    (bypasses RLS for this check).
    """
    client = service_client()
    resp = (
        client.table("memberships")
        .select("organisation_id, role, organisations(status)")
        .eq("user_id", str(user.user_id))
        .limit(1)
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="no membership")
    org_status = (resp.data[0].get("organisations") or {}).get("status")
    if org_status != "internal":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="internal only")
    return user


@router.post("/ingest/world-bank", response_model=IngestResultOut)
def ingest_world_bank(
    req: WorldBankIngestRequest,
    user: CurrentUser = Depends(_require_internal),
) -> IngestResultOut:
    client = service_client()
    repo = RawObservationRepository(client)
    wb = WorldBankClient()
    service = IngestionService(wb_client=wb, repo=repo)

    try:
        return service.ingest_world_bank(
            variable_codes=req.variables,
            start_year=req.start_year or req.year,
            end_year=req.end_year or req.year,
            user_id=user.user_id,
            notes=req.notes,
        )
    except UnknownVariable as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
