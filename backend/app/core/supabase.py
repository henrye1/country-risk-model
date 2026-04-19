from __future__ import annotations
from functools import lru_cache
from supabase import Client, create_client
from supabase.client import ClientOptions

from app.core.settings import get_settings


@lru_cache
def anon_client() -> Client:
    s = get_settings()
    return create_client(s.supabase_url, s.supabase_anon_key)


@lru_cache
def service_client() -> Client:
    s = get_settings()
    # Service-role bypasses RLS. Use only for internal admin / fan-out work.
    return create_client(s.supabase_url, s.supabase_service_role_key)


def user_client(jwt: str) -> Client:
    """Return a client that executes queries as the given user (respects RLS)."""
    s = get_settings()
    options = ClientOptions(headers={"Authorization": f"Bearer {jwt}"})
    return create_client(s.supabase_url, s.supabase_anon_key, options=options)
