"""Authentication and authorization."""

from fastapi import Depends, HTTPException, status
import os


async def verify_api_key(authorization: str = None) -> str:
    """Verify API key from Authorization header."""

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
        )

    # Extract Bearer token
    parts = authorization.split()
    if len(parts) != 2 or parts[0] != "Bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format",
        )

    token = parts[1]
    valid_token = os.getenv("DEMO_API_KEY", "sk-demo-12345")

    if token != valid_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    return token
