"""FastAPI app: `uvicorn cisum.api.main:app`."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .config import get_settings
from .db import init_db
from .deps import CSRF_HEADER, SESSION_COOKIE
from .routes import auth, sharing, songs, uploads

log = logging.getLogger(__name__)
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        init_db()
        yield

    app = FastAPI(title="Cisum", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json", lifespan=lifespan)

    @app.middleware("http")
    async def csrf_guard(request: Request, call_next):
        # Cookie-authenticated writes must carry a custom header, which a cross-site
        # form or image can't add (and cross-site fetch can't without passing CORS).
        if (
            request.url.path.startswith("/api/")
            and request.method not in SAFE_METHODS
            and SESSION_COOKIE in request.cookies
            and not request.headers.get("authorization")
            and request.headers.get(CSRF_HEADER) != "1"
        ):
            return JSONResponse({"detail": "missing CSRF header"}, status_code=403)
        return await call_next(request)

    origins = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()]
    if origins:
        app.add_middleware(
            CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
        )

    for router in (auth.router, uploads.router, songs.router, sharing.router):
        app.include_router(router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    _mount_web(app, settings.web_dist)
    return app


def _mount_web(app: FastAPI, configured: Path | None) -> None:
    """Serve the built single-page app, falling back to index.html for client routes."""
    dist = configured or Path(__file__).resolve().parents[3] / "web" / "dist"
    index = dist / "index.html"
    if not index.is_file():
        return

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        candidate = (dist / path).resolve()
        if path and dist.resolve() in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index)


app = create_app()
