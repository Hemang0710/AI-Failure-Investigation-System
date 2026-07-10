"""URL normalization for managed Postgres providers (Neon/Supabase/Render)."""

from database import _build_async_engine_url


def test_neon_url_coerced_to_asyncpg_with_ssl():
    url, args = _build_async_engine_url(
        "postgresql://u:p@ep-x.aws.neon.tech/db?sslmode=require&channel_binding=require"
    )
    assert url.startswith("postgresql+asyncpg://")
    assert "sslmode" not in url and "channel_binding" not in url
    assert "ssl" in args  # SSL requirement translated to a context


def test_bare_postgres_scheme_coerced():
    url, _ = _build_async_engine_url("postgres://u:p@host/db")
    assert url.startswith("postgresql+asyncpg://")


def test_local_url_unchanged_no_ssl():
    original = "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_failures"
    url, args = _build_async_engine_url(original)
    assert url == original
    assert args == {}


def test_sqlite_untouched():
    url, args = _build_async_engine_url("sqlite+aiosqlite:///./test.db")
    assert url == "sqlite+aiosqlite:///./test.db"
    assert args == {}


def test_db_ssl_env_forces_ssl(monkeypatch):
    monkeypatch.setenv("DB_SSL", "require")
    _, args = _build_async_engine_url("postgresql+asyncpg://u:p@host/db")
    assert "ssl" in args
