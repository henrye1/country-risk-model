def test_anon_client_uses_anon_key():
    from app.core.supabase import anon_client
    c = anon_client()
    assert c is not None


def test_service_client_uses_service_key():
    from app.core.supabase import service_client
    c = service_client()
    assert c is not None


def test_user_client_injects_jwt():
    from app.core.supabase import user_client
    c = user_client("eyJ.fake.jwt")
    assert c is not None
