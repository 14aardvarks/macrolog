"""Photos on foods and recipes.

Files live in a photos/ folder next to the database (created on demand), never in the database: foods.photo and
meals.photo hold only the file name (null = none). Names are random (secrets.token_urlsafe) and change on every
replace, so a served photo can be cached as immutable. One photo per item; replacing or removing deletes the old file.

Every upload is decoded with Pillow, whatever the client says about it: JPEG, PNG or WebP only (magic bytes and the
decoded format), at most photo_max_mb raw and PHOTO_MAX_PIXELS pixels (decompression bombs), orientation applied, then
EXIF and every other metadata dropped, the longest side cut to MAX_SIDE and re-encoded as JPEG. The admin switch
allow_photos (default off) hides the feature: uploads answer 403 and photos are not served.
"""
from __future__ import annotations

import io
import logging
import os
import re
import secrets
import warnings
from pathlib import Path
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError

from . import config, core, db, deps

log = logging.getLogger("macrolog.photos")

router = APIRouter(prefix="/api", dependencies=[Depends(deps.current_user)])
CurrentUser = Annotated[dict, Depends(deps.current_user)]

MAX_SIDE = 1600  # longest side after resizing, in pixels
QUALITIES = (82, 72, 62)  # JPEG quality, lowered only while the result is above TARGET_BYTES
TARGET_BYTES = 1024 * 1024
PHOTO_MAX_PIXELS = 50_000_000  # anything larger is refused before it is decoded
Image.MAX_IMAGE_PIXELS = PHOTO_MAX_PIXELS
FORMATS = {"JPEG", "PNG", "WEBP"}
NAME_RE = re.compile(r"[A-Za-z0-9_-]{16,64}\.jpg")
CACHE = "private, max-age=31536000, immutable"
OFF_MESSAGE = "Photos are turned off on this server."
BAD_IMAGE = "That file is not a readable JPEG, PNG or WebP image."


# ---------- settings ----------

def enabled() -> bool:
    return config.flag("allow_photos")


def max_mb() -> int:
    spec = config.MANAGED["photo_max_mb"]
    return int(min(spec.hi, max(spec.lo, config.integer("photo_max_mb"))))


def require_enabled() -> None:
    if not enabled():
        raise HTTPException(403, OFF_MESSAGE)


# ---------- files ----------

def photo_dir() -> Path:
    return Path(db.db_path()).parent / "photos"


def valid_name(name) -> bool:
    return isinstance(name, str) and NAME_RE.fullmatch(name) is not None


def path_of(name: str) -> Path:
    if not valid_name(name):
        raise ValueError("bad photo name")
    return photo_dir() / name


def write_file(data: bytes) -> str:
    """Store data under a new random name (temp file, then rename, so a reader never sees half a file)."""
    folder = photo_dir()
    folder.mkdir(parents=True, exist_ok=True)
    name = secrets.token_urlsafe(24) + ".jpg"
    tmp = folder / (name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, folder / name)
    return name


def remove_file(name: Optional[str]) -> None:
    """Delete a stored photo. Unknown, invalid or already missing names are ignored."""
    if not valid_name(name):
        return
    try:
        path_of(name).unlink()
    except FileNotFoundError:
        pass
    except OSError as e:
        log.warning("Could not delete photo %s: %s", name, e)


def copy_file(name: Optional[str]) -> Optional[str]:
    """A copy of a stored photo under a new name (Duplicate), or None when there is nothing to copy."""
    if not valid_name(name):
        return None
    try:
        data = path_of(name).read_bytes()
    except OSError:
        return None
    return write_file(data)


# ---------- image processing ----------

def sniff(data: bytes) -> Optional[str]:
    if data[:3] == b"\xff\xd8\xff":
        return "JPEG"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "PNG"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    return None


def _flatten(im: Image.Image) -> Image.Image:
    """RGB on a white background (transparent PNG and WebP would turn black in a JPEG)."""
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.getchannel("A"))
        return bg
    return im.convert("RGB")


def process(data: bytes) -> bytes:
    """Validated, oriented, metadata free JPEG of at most MAX_SIDE pixels on its longest side. Raises HTTPException 400."""
    if sniff(data) is None:
        raise HTTPException(400, "Only JPEG, PNG and WebP photos are allowed.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as im:
                if im.format not in FORMATS:
                    raise HTTPException(400, "Only JPEG, PNG and WebP photos are allowed.")
                w, h = im.size
                if w < 1 or h < 1 or w * h > PHOTO_MAX_PIXELS:
                    raise HTTPException(400, f"That photo is too large ({w} x {h} pixels). The limit is {PHOTO_MAX_PIXELS // 1_000_000} megapixels.")
                if im.format == "JPEG":
                    im.draft("RGB", (MAX_SIDE, MAX_SIDE))  # decode big JPEGs at a reduced scale (never below MAX_SIDE)
                im.load()
                out = ImageOps.exif_transpose(im)  # orientation first, before the EXIF data is dropped
                out = _flatten(out)
                out.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    except HTTPException:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(400, f"That photo is too large. The limit is {PHOTO_MAX_PIXELS // 1_000_000} megapixels.")
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, EOFError, MemoryError):
        raise HTTPException(400, BAD_IMAGE)
    best = b""
    for q in QUALITIES:
        buf = io.BytesIO()
        out.save(buf, "JPEG", quality=q, optimize=True)  # no exif, icc or comment passed: all metadata is dropped
        best = buf.getvalue()
        if len(best) <= TARGET_BYTES:
            break
    return best


async def read_upload(photo: Optional[UploadFile]) -> bytes:
    if photo is None:
        raise HTTPException(400, "Attach a photo.")
    limit = max_mb() * 1024 * 1024
    data = await photo.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"That photo is larger than {max_mb()} MB.")
    if not data:
        raise HTTPException(400, "The photo is empty.")
    return await run_in_threadpool(process, data)


# ---------- permissions ----------

def writable_food(c, user: dict, food_id: int):
    """The food's creator (a custom or Claude food) or an admin may change its photo. Shared Open Food Facts and USDA foods
    have no creator, so only an admin may."""
    row = c.execute("SELECT * FROM foods WHERE id=?", (food_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Food not found")
    own = row["created_by"] == user["id"] and row["source"] in ("custom", "ai")
    if not own and not user.get("is_admin"):
        raise HTTPException(403, "Only the person who created this food or an admin can change its photo.")
    return row


def _set(table: str, item_id: int, name: Optional[str], c) -> Optional[str]:
    old = c.execute(f"SELECT photo FROM {table} WHERE id=?", (item_id,)).fetchone()["photo"]
    c.execute(f"UPDATE {table} SET photo=? WHERE id=?", (name, item_id))
    return old


def _replace(table: str, item_id: int, data: bytes, check) -> str:
    """Write the new file, point the row at it, then delete the old file once the row is saved."""
    name = write_file(data)
    try:
        with db.conn() as c:
            check(c)
            old = _set(table, item_id, name, c)
    except BaseException:
        remove_file(name)
        raise
    if old != name:
        remove_file(old)
    return name


def _remove(table: str, item_id: int, check) -> None:
    with db.conn() as c:
        check(c)
        old = _set(table, item_id, None, c)
    remove_file(old)


# ---------- routes ----------

@router.get("/photo-config")
def photo_config(user: CurrentUser):
    return {"enabled": enabled(), "max_mb": max_mb(), "max_side": MAX_SIDE}


@router.post("/foods/{food_id}/photo")
async def put_food_photo(food_id: int, user: CurrentUser, photo: Optional[UploadFile] = File(None)):
    require_enabled()
    with db.conn() as c:
        writable_food(c, user, food_id)  # refuse before reading the upload
    data = await read_upload(photo)
    name = _replace("foods", food_id, data, lambda c: writable_food(c, user, food_id))
    return {"photo": name}


@router.delete("/foods/{food_id}/photo")
def delete_food_photo(food_id: int, user: CurrentUser):
    require_enabled()
    _remove("foods", food_id, lambda c: writable_food(c, user, food_id))
    return {"photo": None}


@router.post("/meals/{meal_id}/photo")
async def put_meal_photo(meal_id: int, user: CurrentUser, photo: Optional[UploadFile] = File(None)):
    require_enabled()
    with db.conn() as c:
        core.writable_meal(c, user, meal_id)
    data = await read_upload(photo)
    name = _replace("meals", meal_id, data, lambda c: core.writable_meal(c, user, meal_id))
    return {"photo": name}


@router.delete("/meals/{meal_id}/photo")
def delete_meal_photo(meal_id: int, user: CurrentUser):
    require_enabled()
    _remove("meals", meal_id, lambda c: core.writable_meal(c, user, meal_id))
    return {"photo": None}


def can_see(c, uid: int, name: str) -> bool:
    """Any signed in user sees a food photo (foods are one shared table and GET /api/foods/{id} answers every food).
    A recipe photo: my own recipe (Recently Deleted included, until it is purged) or another user's shared recipe that is
    not deleted."""
    if c.execute("SELECT 1 FROM foods WHERE photo=?", (name,)).fetchone():
        return True
    return c.execute("SELECT 1 FROM meals WHERE photo=? AND (user_id=? OR (shared=1 AND deleted_at IS NULL))",
                     (name, uid)).fetchone() is not None


@router.get("/photos/{name}")
def get_photo(name: str, user: CurrentUser):
    if not valid_name(name):
        raise HTTPException(404, "Photo not found")
    require_enabled()
    with db.conn() as c:
        if not can_see(c, user["id"], name):
            raise HTTPException(404, "Photo not found")
    path = path_of(name)
    if not path.is_file():
        raise HTTPException(404, "Photo not found")
    return FileResponse(path, media_type="image/jpeg",
                        headers={"Cache-Control": CACHE, "X-Content-Type-Options": "nosniff"})
