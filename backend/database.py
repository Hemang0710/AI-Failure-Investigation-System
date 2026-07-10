"""Database connection and session management."""

from sqlalchemy import create_engine, event, select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool
import os
from typing import AsyncGenerator

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/ai_failures"
)

ASYNC_DATABASE_URL = os.getenv(
    "ASYNC_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_failures"
)

Base = declarative_base()

engine = create_async_engine(
    ASYNC_DATABASE_URL,
    echo=os.getenv("SQL_ECHO", "false").lower() == "true",
    future=True,
    pool_pre_ping=True,
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
