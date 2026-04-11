from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import structlog

from config import settings
from routers import interpret, chat, extract, ocr, wearables
from services.memory import init_graphiti, close_graphiti

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("health AI service starting", env=settings.ENV)
    await init_graphiti()
    yield
    await close_graphiti()
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
