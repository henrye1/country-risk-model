from app.core.settings import Settings


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "secret")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173,http://foo.test")

    s = Settings()

    assert s.supabase_url == "https://x.supabase.co"
    assert s.supabase_anon_key == "anon"
    assert s.supabase_service_role_key == "service"
    assert s.supabase_jwt_secret == "secret"
    assert s.cors_origins == ["http://localhost:5173", "http://foo.test"]
    assert s.log_level == "INFO"
