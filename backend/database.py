"""Database connection and session management."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
import os
import ssl
from typing import AsyncGenerator
from urllib.parse import parse_qsl, urlencode

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/ai_failures"
)


def _build_async_engine_url(raw: str):
    """Normalize a database URL for the asyncpg driver and derive connect args.

    Accepts URLs as pasted from managed providers (Neon, Supabase, Render):
    coerces a bare ``postgres://``/``postgresql://`` URL to ``+asyncpg``, and
    strips libpq-only query params (``sslmode``, ``channel_binding``) that
    asyncpg rejects - translating an SSL requirement into an SSL context.

    Only the query string is rewritten, so SQLite and other URLs pass through
    untouched.
    """
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://"):]
    if raw.startswith("postgresql://"):
        raw = "postgresql+asyncpg://" + raw[len("postgresql://"):]

    wants_ssl = os.getenv("DB_SSL", "").lower() in ("require", "true", "1")

    if "asyncpg" in raw and "?" in raw:
        base, _, query_string = raw.partition("?")
        kept = []
        for key, value in parse_qsl(query_string):
            if key == "sslmode":
                wants_ssl = wants_ssl or value in ("require", "verify-ca", "verify-full")
            elif key == "channel_binding":
                continue  # asyncpg negotiates this itself; the param would error
            else:
                kept.append((key, value))
        raw = base + (f"?{urlencode(kept)}" if kept else "")

    connect_args = {}
    if wants_ssl and "asyncpg" in raw:
        connect_args["ssl"] = ssl.create_default_context()
    return raw, connect_args


ASYNC_DATABASE_URL, _CONNECT_ARGS = _build_async_engine_url(
    os.getenv(
        "ASYNC_DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_failures",
    )
)

Base = declarative_base()

engine = create_async_engine(
    ASYNC_DATABASE_URL,
    echo=os.getenv("SQL_ECHO", "false").lower() == "true",
    future=True,
    pool_pre_ping=True,
    connect_args=_CONNECT_ARGS,
)

AsyncSessionLocal = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get database session for dependency injection."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """Initialize database tables and seed the default user and API key."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Deferred imports: models/auth depend on Base defined above
    from models import User, APIKey
    from auth import hash_api_key
    from sqlalchemy import func
    import secrets

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.username == "default"))
        user = result.scalar_one_or_none()

        if not user:
            user = User(username="default", email="default@localhost")
            session.add(user)
            await session.flush()

        bootstrap_key = os.getenv("BOOTSTRAP_API_KEY")
        if bootstrap_key:
            key_hash = hash_api_key(bootstrap_key)
            existing = await session.execute(
                select(APIKey).where(APIKey.key_hash == key_hash)
            )
            if existing.scalar_one_or_none() is None:
                session.add(APIKey(user_id=user.id, key_hash=key_hash, name="bootstrap"))
        else:
            active_keys = await session.scalar(
                select(func.count()).select_from(APIKey).where(APIKey.is_active.is_(True))
            )
            if not active_keys:
                new_key = "sk-" + secrets.token_urlsafe(32)
                session.add(
                    APIKey(user_id=user.id, key_hash=hash_api_key(new_key), name="generated")
                )
                print(
                    "\n" + "=" * 64 + "\n"
                    "No API key configured. Generated one for this instance:\n\n"
                    f"    {new_key}\n\n"
                    "Store it now - only its hash is saved and it will not be\n"
                    "shown again. Set BOOTSTRAP_API_KEY to provision a known key.\n"
                    + "=" * 64 + "\n"
                )

        await session.commit()


async def drop_db():
    """Drop all database tables (testing only)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
