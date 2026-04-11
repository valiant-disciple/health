from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import structlog

from config import settings
from logging_config import configure_logging
from routers import interpret, chat, extract, ocr, wearables
from services.memory import init_graphiti, close_graphiti
from services.tracing import flush as flush_traces

configure_logging(env=settings.ENV)
log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("health AI service starting", env=settings.ENV)
    await init_graphiti()
    yield
    await close_graphiti()
    flush_traces()
    log.info("health AI service stopped")


app = FastAPI(
    title="health AI Service",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.ENV != "production" else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-User-Id"],
    allow_credentials=True,
)

app.include_router(interpret.router, prefix="/interpret", tags=["interpret"])
app.include_router(chat.router,      prefix="/chat",      tags=["chat"])
app.include_router(extract.router,   prefix="/extract",   tags=["extract"])
app.include_router(ocr.router,       prefix="/ocr",       tags=["ocr"])
app.include_router(wearables.router, prefix="/wearables", tags=["wearables"])


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "health-ai"}


@app.get("/health/detailed")
async def health_check_detailed():
    """
    Probe all external dependencies. Returns overall status + per-service latency.
    Not cached — every call does live probes.
    """
    from services.health_check import run_health_checks
    result = await run_health_checks()
    # Return 503 if any critical dependency is unavailable
    status_code = 503 if result["status"] == "unavailable" else 200
    from fastapi.responses import JSONResponse
    return JSONResponse(content=result, status_code=status_code)
