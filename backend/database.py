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
    """Initialize database tables and seed default data."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed default user and API key
    async with AsyncSessionLocal() as session:
        from models import User, APIKey

        # Check if default user exists
        result = await session.execute(select(User).where(User.username == "default"))
        user = result.scalar_one_or_none()

        if not user:
            user = User(username="default", email="default@localhost")
            session.add(user)
            await session.flush()

            # Add API key
            api_key = APIKey(user_id=user.id, key_hash="sk-demo-12345", name="demo")
            session.add(api_key)
            await session.commit()


async def drop_db():
    """Drop all database tables (testing only)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
