"""FastAPI application entry point."""
import logging
import os
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from app.db import init_db
from app.scheduler import start_scheduler, stop_scheduler
from app.auth import verify_token
from app.api import subscriptions, search, tasks, library, settings, discover, online
from app.api import auth as auth_api
from app.api import logs as logs_api

WEB_DIR = Path(__file__).parent.parent / "web"
WEB_DIST_DIR = WEB_DIR / "dist"
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# Configure logging
log_file = LOG_DIR / "music_sub.log"
file_handler = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
file_handler.setLevel(logging.INFO)

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(file_handler)

# Also log to stdout
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S"))
root_logger.addHandler(stream_handler)

# Paths that don't require authentication
PUBLIC_PATHS = {"/api/auth/login", "/api/health", "/"}


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
    version="0.6.30",
    lifespan=lifespan,
)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Check JWT token for protected routes."""
    path = request.url.path
    # Allow public paths and static assets
    if path in PUBLIC_PATHS or not path.startswith("/api/"):
        return await call_next(request)
    # Allow cover image endpoints (used as CSS background-image, no auth header)
    if path.startswith("/api/library/album-cover") or path.startswith("/api/library/cover/") or path.startswith("/api/library/stream/"):
        return await call_next(request)
    # Allow health check
    if path == "/api/health":
        return await call_next(request)

    # Check Authorization header
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse(status_code=401, content={"detail": "未登录"})

    token = auth_header[7:]
    username = verify_token(token)
    if not username:
        return JSONResponse(status_code=401, content={"detail": "登录已过期"})

    return await call_next(request)


app.include_router(auth_api.router, prefix="/api/auth", tags=["auth"])
app.include_router(subscriptions.router, prefix="/api/subscriptions", tags=["subscriptions"])
app.include_router(search.router, prefix="/api/search", tags=["search"])
app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"])
app.include_router(library.router, prefix="/api/library", tags=["library"])
app.include_router(settings.router, prefix="/api/settings", tags=["settings"])
app.include_router(discover.router, prefix="/api/discover", tags=["discover"])
app.include_router(logs_api.router, prefix="/api/logs", tags=["logs"])
app.include_router(online.router, prefix="/api/online", tags=["online"])


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "0.6.30"}


# Serve new Vue SPA (web/dist/) with fallback to legacy (web/index.html)
from fastapi.staticfiles import StaticFiles

if WEB_DIST_DIR.exists():
    # Serve static assets from dist
    app.mount("/assets", StaticFiles(directory=WEB_DIST_DIR / "assets"), name="dist-assets")


@app.get("/{full_path:path}")
def serve_frontend(full_path: str):
    """Serve Vue SPA. Fallback to legacy index.html if dist not available."""
    # Try new frontend first
    if WEB_DIST_DIR.exists():
        # Check if specific file exists in dist
        file_path = WEB_DIST_DIR / full_path
        if full_path and file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        # SPA fallback: serve index.html for all routes
        return FileResponse(WEB_DIST_DIR / "index.html")
    # Legacy fallback
    return FileResponse(WEB_DIR / "index.html")
