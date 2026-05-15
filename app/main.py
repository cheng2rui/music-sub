"""FastAPI application entry point."""
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.db import init_db
from app.scheduler import start_scheduler, stop_scheduler
from app.api import subscriptions, search, tasks, library, settings, discover

WEB_DIR = Path(__file__).parent.parent / "web"


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
    version="0.3.0",
    lifespan=lifespan,
)

app.include_router(subscriptions.router, prefix="/api/subscriptions", tags=["subscriptions"])
app.include_router(search.router, prefix="/api/search", tags=["search"])
app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"])
app.include_router(library.router, prefix="/api/library", tags=["library"])
app.include_router(settings.router, prefix="/api/settings", tags=["settings"])
app.include_router(discover.router, prefix="/api/discover", tags=["discover"])


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "0.3.0"}


@app.get("/")
def root():
    """Serve Web UI."""
    return FileResponse(WEB_DIR / "index.html")
