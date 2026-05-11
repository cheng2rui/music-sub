"""FastAPI application entry point."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.db import init_db
from app.scheduler import start_scheduler, stop_scheduler
from app.api import subscriptions, search, tasks, library


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown."""
    init_db()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(
    title="Music Sub",
    description="音乐订阅下载管理系统 - PT站搜索订阅 + QB下载 + 硬链接整理 + 自动刮削",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(subscriptions.router, prefix="/api/subscriptions", tags=["subscriptions"])
app.include_router(search.router, prefix="/api/search", tags=["search"])
app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"])
app.include_router(library.router, prefix="/api/library", tags=["library"])


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "0.1.0"}


@app.get("/")
def root():
    return {
        "name": "Music Sub",
        "version": "0.1.0",
        "docs": "/docs",
    }
