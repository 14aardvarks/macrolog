"""App wiring. Run with: uvicorn app.main:create_app --factory"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from . import ai, auth, core, db

MIN_SECRET_LEN = 32
STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    with db.conn() as c:
        db.init_shared(c)
        for module in (auth, core, ai):
            module.init(c)
    auth.bootstrap_admin()
    yield


def create_app() -> FastAPI:
    secret = os.environ.get("SECRET_KEY", "")
    if len(secret) < MIN_SECRET_LEN:
        raise RuntimeError(f"SECRET_KEY must be set and at least {MIN_SECRET_LEN} characters long. "
                           'Generate one with: python3 -c "import secrets; print(secrets.token_urlsafe(48))"')
    app = FastAPI(title="Macrolog", lifespan=lifespan, dependencies=[Depends(auth.require_same_origin)])
    app.add_middleware(
        SessionMiddleware,
        secret_key=secret,
        session_cookie="macrolog_session",
        max_age=60 * 60 * 24 * 90,
        same_site="lax",
        https_only=os.environ.get("COOKIE_SECURE", "0") == "1",
    )
    app.include_router(auth.router)
    app.include_router(core.router)
    app.include_router(ai.router)

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/", StaticFiles(directory=STATIC), name="static")
    return app

