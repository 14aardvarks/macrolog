"""App wiring. Run with: uvicorn app.main:create_app --factory"""
from __future__ import annotations

import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from . import admin, ai, auth, config, core, db, recipe_ai

MIN_SECRET_LEN = 32
STATIC = Path(__file__).parent / "static"


def resolve_secret_key() -> str:
    """SECRET_KEY from the environment, else a key generated once and kept next to the database."""
    secret = os.environ.get("SECRET_KEY", "")
    if not secret:
        secret = _stored_secret(Path(db.db_path()).parent / "secret_key")
        os.environ["SECRET_KEY"] = secret
    if len(secret) < MIN_SECRET_LEN:
        raise RuntimeError(f"SECRET_KEY must be at least {MIN_SECRET_LEN} characters long. "
                           'Generate one with: python3 -c "import secrets; print(secrets.token_urlsafe(48))"')
    return secret


def _stored_secret(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return path.read_text().strip()
    with os.fdopen(fd, "w") as f:
        f.write(secrets.token_urlsafe(48))
    return path.read_text().strip()


@asynccontextmanager
async def lifespan(app: FastAPI):
    with db.conn() as c:
        db.init_shared(c)
        for module in (config, auth, core, ai, admin):
            module.init(c)
    auth.bootstrap_admin()
    yield


async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """422 without the submitted values, so a rejected password or key is never echoed back."""
    detail = [{"type": e.get("type"), "loc": list(e.get("loc", ())), "msg": e.get("msg")} for e in exc.errors()]
    return JSONResponse({"detail": detail}, status_code=422)


def create_app() -> FastAPI:
    secret = resolve_secret_key()
    app = FastAPI(title="Macrolog", lifespan=lifespan, dependencies=[Depends(auth.require_same_origin)])
    app.add_exception_handler(RequestValidationError, validation_error)
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
    app.include_router(admin.router)
    app.include_router(recipe_ai.router)

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/", StaticFiles(directory=STATIC), name="static")
    return app

