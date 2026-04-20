from __future__ import annotations
import logging
from functools import lru_cache
from uuid import UUID

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.core.settings import Settings, get_settings
from app.schemas.user import CurrentUser

_bearer = HTTPBearer(auto_error=False)
_logger = logging.getLogger("uvicorn.error")


@lru_cache
def _fetch_jwks(supabase_url: str) -> dict:
    """Fetch + cache Supabase project's JWKS (public keys used to verify ES256 tokens)."""
    url = f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    resp = httpx.get(url, timeout=10.0)
    resp.raise_for_status()
    return resp.json()


def _key_for_kid(jwks: dict, kid: str) -> dict | None:
    for k in jwks.get("keys", []):
        if k.get("kid") == kid:
            return k
    return None


def _verify(token: str, settings: Settings) -> dict:
    """Verify a Supabase JWT. Supports HS256 (legacy secret) and ES256 (JWKS lookup)."""
    header = jwt.get_unverified_header(token)
    alg = header.get("alg")

    if alg == "HS256":
        return jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )

    if alg == "ES256":
        jwks = _fetch_jwks(settings.supabase_url)
        kid = header.get("kid")
        key = _key_for_kid(jwks, kid) if kid else None
        if key is None:
            raise JWTError(f"no public key with kid={kid} in project JWKS")
        return jwt.decode(
            token,
            key,
            algorithms=["ES256"],
            audience="authenticated",
        )

    raise JWTError(f"unsupported JWT alg: {alg}")


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    if creds is None or not creds.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")
    try:
        payload = _verify(creds.credentials, settings)
    except JWTError as exc:
        try:
            header = jwt.get_unverified_header(creds.credentials)
        except Exception:
            header = {}
        _logger.warning(
            "JWT decode failed: %s | header alg=%s kid=%s",
            exc, header.get("alg"), header.get("kid"),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"invalid token: {exc}",
        ) from exc

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token missing sub claim")

    return CurrentUser(user_id=UUID(sub), email=payload.get("email"), raw_jwt=creds.credentials)
