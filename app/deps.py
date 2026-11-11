"""Shared FastAPI dependencies."""
from __future__ import annotations

from fastapi import HTTPException, Request

from . import db


def current_user(request: Request) -> dict:
    """The signed-in user from the session cookie, or 401."""
    uid = request.session.get("uid")
    if not uid:
        raise HTTPException(401, "Not signed in")
    with db.conn() as c:
        row = c.execute("SELECT id, username, display_name, session_version FROM users WHERE id=?", (uid,)).fetchone()
    if not row or request.session.get("sv", 0) != row["session_version"]:
        request.session.clear()
        raise HTTPException(401, "Not signed in")
    user = dict(row)
    del user["session_version"]
    return user
