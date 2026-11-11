"""Shared FastAPI dependencies."""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from . import db


def current_user(request: Request) -> dict:
    """The signed-in, enabled user from the session cookie, or 401."""
    uid = request.session.get("uid")
    if not uid:
        raise HTTPException(401, "Not signed in")
    with db.conn() as c:
        row = c.execute("SELECT id, username, display_name, session_version, is_admin, disabled FROM users WHERE id=?",
                        (uid,)).fetchone()
    if not row or row["disabled"] or request.session.get("sv", 0) != row["session_version"]:
        request.session.clear()
        raise HTTPException(401, "Not signed in")
    return {"id": row["id"], "username": row["username"], "display_name": row["display_name"],
            "is_admin": bool(row["is_admin"])}


def require_admin(user: dict = Depends(current_user)) -> dict:
    """current_user, and 403 unless that user is an administrator."""
    if not user.get("is_admin"):
        raise HTTPException(403, "Administrator access required")
    return user
