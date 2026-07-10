"""Authentication and authorization."""

import hashlib

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import APIKey

bearer_scheme = HTTPBearer(auto_error=False)


def hash_api_key(key: str) -> str:
    """Hash an API key for storage and lookup. Only hashes are persisted."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


async def verify_api_key(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> APIKey:
    """Authenticate a request via its Bearer API key.

    Looks up the SHA-256 hash of the presented key in the api_keys table
    and returns the matching row so routes can attribute data to a user.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    key_hash = hash_api_key(credentials.credentials)
    result = await db.execute(
        select(APIKey).where(APIKey.key_hash == key_hash, APIKey.is_active.is_(True))
    )
    api_key = result.scalar_one_or_none()

    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return api_key
