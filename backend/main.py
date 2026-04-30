"""FastAPI application for AI Failure Investigation System."""

from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from datetime import datetime
from contextlib import asynccontextmanager
import os
import uuid

from database import init_db, get_db
from routers import events, failures, patterns, models, stats, health
from auth import verify_api_key


# Database initialization
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("Initializing database...")
    await init_db()
    print("Database initialized successfully")
    yield
    # Shutdown
    print("Application shutting down...")


app = FastAPI(
    title="AI Failure Investigation System",
    description="Observability platform for tracking and analyzing LLM failures",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:8501").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Middleware for request ID tracking
@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


# Include routers
app.include_router(health.router)
app.include_router(events.router, prefix="/api/v1", tags=["events"])
app.include_router(failures.router, prefix="/api/v1", tags=["failures"])
app.include_router(patterns.router, prefix="/api/v1", tags=["patterns"])
app.include_router(models.router, prefix="/api/v1", tags=["models"])
app.include_router(stats.router, prefix="/api/v1", tags=["stats"])


# Global exception handler
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.detail if isinstance(exc.detail, str) else "unknown_error",
                "message": str(exc.detail),
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "request_id": getattr(request.state, "request_id", None),
            }
        },
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", 8000)),
        reload=os.getenv("ENV", "development") == "development",
    )
