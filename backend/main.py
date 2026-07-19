"""FastAPI application for AI Failure Investigation System."""

from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from datetime import datetime, timezone
from contextlib import asynccontextmanager, suppress
import asyncio
import os
import uuid

from database import init_db
from routers import events, failures, patterns, models, stats, health, correlations, feedback, recommendations
from auth import verify_api_key
from ratelimit import default_rate_limit
from retention import retention_loop, DATA_RETENTION_DAYS


# Database initialization
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("Initializing database...")
    await init_db()
    print("Database initialized successfully")

    # Background data-retention sweep (only when a retention window is set)
    retention_task = None
    if DATA_RETENTION_DAYS > 0:
        retention_task = asyncio.create_task(retention_loop())

    yield

    # Shutdown
    print("Application shutting down...")
    if retention_task is not None:
        retention_task.cancel()
        with suppress(asyncio.CancelledError):
            await retention_task


app = FastAPI(
    title="AI Failure Investigation System",
    description="Observability platform for tracking and analyzing LLM failures",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS Configuration.
# When CORS_ORIGINS is the wildcard we must NOT also allow credentials: the
# "*" + credentials combination is rejected by browsers and makes Starlette
# reflect *any* Origin back with Access-Control-Allow-Credentials, which is an
# open-CORS footgun. Auth is via Bearer token (no cookies), so credentials are
# not needed in the wildcard case anyway.
_cors_origins = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:8501").split(",")
    if o.strip()
]
_cors_allow_all = "*" in _cors_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=not _cors_allow_all,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request body size cap. Checks Content-Length only; a reverse proxy should
# additionally enforce this for chunked requests in production.
MAX_REQUEST_BYTES = int(os.getenv("MAX_REQUEST_BYTES", str(10 * 1024 * 1024)))


@app.middleware("http")
async def limit_request_size(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            too_large = int(content_length) > MAX_REQUEST_BYTES
        except ValueError:
            too_large = True
        if too_large:
            return JSONResponse(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                content={
                    "error": {
                        "code": "request_too_large",
                        "message": f"Request body exceeds maximum of {MAX_REQUEST_BYTES} bytes",
                        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    }
                },
            )
    return await call_next(request)


# Middleware for request ID tracking
@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


# Include routers. Every /api/v1 route is rate limited and requires a valid
# API key; only health is open. The rate limit runs first so floods of bad
# credentials never reach the database.
protected = [Depends(default_rate_limit), Depends(verify_api_key)]
app.include_router(health.router)
app.include_router(events.router, prefix="/api/v1", tags=["events"], dependencies=protected)
app.include_router(failures.router, prefix="/api/v1", tags=["failures"], dependencies=protected)
app.include_router(patterns.router, prefix="/api/v1", tags=["patterns"], dependencies=protected)
app.include_router(models.router, prefix="/api/v1", tags=["models"], dependencies=protected)
app.include_router(stats.router, prefix="/api/v1", tags=["stats"], dependencies=protected)
app.include_router(correlations.router, prefix="/api/v1", tags=["correlations"], dependencies=protected)
app.include_router(feedback.router, prefix="/api/v1", tags=["feedback"], dependencies=protected)
app.include_router(recommendations.router, prefix="/api/v1", tags=["recommendations"], dependencies=protected)


# Global exception handler
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.detail if isinstance(exc.detail, str) else "unknown_error",
                "message": str(exc.detail),
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "request_id": getattr(request.state, "request_id", None),
            }
        },
        # Preserve headers such as Retry-After (429) and WWW-Authenticate (401)
        headers=getattr(exc, "headers", None),
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", 8000)),
        reload=os.getenv("ENV", "development") == "development",
    )
