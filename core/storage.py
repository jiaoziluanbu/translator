"""SQLite + filesystem storage for shots, OCR blocks, and edit ops.

Data lives under ~/Library/Application Support/LocalTranslator/:
  shots/      original (edited) PNGs
  exports/    PNGs with translation overlay
  db.sqlite   metadata
"""
from __future__ import annotations

import os
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

APP_DIR = Path(os.path.expanduser("~/Library/Application Support/LocalTranslator"))
SHOTS_DIR = APP_DIR / "shots"
EXPORTS_DIR = APP_DIR / "exports"
GALLERY_DIR = APP_DIR / "gallery"
GALLERY_THUMBS = GALLERY_DIR / "thumbs"
DB_PATH = APP_DIR / "db.sqlite"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS shots (
  id          TEXT PRIMARY KEY,
  created_at  INTEGER NOT NULL,
  orig_path   TEXT NOT NULL,
  export_path TEXT,
  src_lang    TEXT NOT NULL,
  tgt_lang    TEXT NOT NULL,
  canvas_x    REAL NOT NULL DEFAULT 0,
  canvas_y    REAL NOT NULL DEFAULT 0,
  width       INTEGER NOT NULL,
  height      INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS text_blocks (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  shot_id    TEXT NOT NULL REFERENCES shots(id) ON DELETE CASCADE,
  bbox_x     REAL NOT NULL,
  bbox_y     REAL NOT NULL,
  bbox_w     REAL NOT NULL,
  bbox_h     REAL NOT NULL,
  src_text   TEXT NOT NULL,
  tgt_text   TEXT NOT NULL,
  confidence REAL
);
CREATE TABLE IF NOT EXISTS edits (
  shot_id    TEXT PRIMARY KEY REFERENCES shots(id) ON DELETE CASCADE,
  ops_json   TEXT NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_shots_created ON shots(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_blocks_shot ON text_blocks(shot_id);
CREATE TABLE IF NOT EXISTS gallery_items (
  id           TEXT PRIMARY KEY,
  name         TEXT NOT NULL,
  kind         TEXT NOT NULL,           -- 'raw' | 'translated'
  src_lang     TEXT NOT NULL DEFAULT '',
  tgt_lang     TEXT NOT NULL DEFAULT '',
  file_path    TEXT NOT NULL,
  thumb_path   TEXT NOT NULL,
  width        INTEGER NOT NULL,
  height       INTEGER NOT NULL,
  canvas_x     REAL NOT NULL DEFAULT 0,
  canvas_y     REAL NOT NULL DEFAULT 0,
  canvas_scale REAL NOT NULL DEFAULT 1,
  created_at   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gallery_created ON gallery_items(created_at DESC);
"""


@dataclass
class Shot:
    id: str
    created_at: int
    orig_path: str
    export_path: str | None
    src_lang: str
    tgt_lang: str
    canvas_x: float
    canvas_y: float
    width: int
    height: int


def _conn() -> sqlite3.Connection:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    SHOTS_DIR.mkdir(exist_ok=True)
    EXPORTS_DIR.mkdir(exist_ok=True)
    GALLERY_DIR.mkdir(exist_ok=True)
    GALLERY_THUMBS.mkdir(exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.execute("PRAGMA foreign_keys = ON")
    return c


def init_db() -> None:
    with _conn() as c:
        c.executescript(_SCHEMA)


def save_shot(orig_png: bytes, blocks: list, src: str, tgt: str,
              width: int, height: int) -> str:
    """Persist a new shot; `blocks` is a list of core.ocr.TextBlock + translations."""
    shot_id = uuid.uuid4().hex
    orig_path = SHOTS_DIR / f"{shot_id}.png"
    orig_path.write_bytes(orig_png)
    now_ms = int(time.time() * 1000)
    with _conn() as c:
        c.executescript(_SCHEMA)
        c.execute(
            "INSERT INTO shots(id,created_at,orig_path,export_path,src_lang,tgt_lang,width,height) "
            "VALUES(?,?,?,NULL,?,?,?,?)",
            (shot_id, now_ms, str(orig_path), src, tgt, width, height),
        )
        for b in blocks:
            c.execute(
                "INSERT INTO text_blocks(shot_id,bbox_x,bbox_y,bbox_w,bbox_h,src_text,tgt_text,confidence) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (shot_id,
                 b["bbox_x"], b["bbox_y"], b["bbox_w"], b["bbox_h"],
                 b["src_text"], b["tgt_text"], b.get("confidence")),
            )
    return shot_id


def update_export(shot_id: str, export_png: bytes) -> None:
    path = EXPORTS_DIR / f"{shot_id}_export.png"
    path.write_bytes(export_png)
    with _conn() as c:
        c.execute("UPDATE shots SET export_path=? WHERE id=?", (str(path), shot_id))


def save_edits(shot_id: str, ops_json: str) -> None:
    now_ms = int(time.time() * 1000)
    with _conn() as c:
        c.execute(
            "INSERT INTO edits(shot_id,ops_json,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(shot_id) DO UPDATE SET ops_json=excluded.ops_json, updated_at=excluded.updated_at",
            (shot_id, ops_json, now_ms),
        )


def list_shots(limit: int = 200) -> list[Shot]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id,created_at,orig_path,export_path,src_lang,tgt_lang,canvas_x,canvas_y,width,height "
            "FROM shots ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [Shot(*r) for r in rows]


def update_canvas_pos(shot_id: str, x: float, y: float) -> None:
    with _conn() as c:
        c.execute("UPDATE shots SET canvas_x=?, canvas_y=? WHERE id=?", (x, y, shot_id))


# ---------- gallery ----------

@dataclass
class GalleryItem:
    id: str
    name: str
    kind: str
    src_lang: str
    tgt_lang: str
    file_path: str
    thumb_path: str
    width: int
    height: int
    canvas_x: float
    canvas_y: float
    canvas_scale: float
    created_at: int


_THUMB_MAX = 400


def _make_thumb(png_bytes: bytes, out_path: Path) -> tuple[int, int]:
    """Write a JPEG thumbnail (max edge=_THUMB_MAX) and return (orig_w, orig_h)."""
    from io import BytesIO
    from PIL import Image
    img = Image.open(BytesIO(png_bytes))
    img.load()
    ow, oh = img.size
    img.thumbnail((_THUMB_MAX, _THUMB_MAX))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.save(out_path, "JPEG", quality=82)
    return ow, oh


def add_gallery_item(png_bytes: bytes, kind: str, *,
                     src_lang: str = "", tgt_lang: str = "",
                     name: str | None = None) -> GalleryItem:
    if kind not in ("raw", "translated"):
        raise ValueError(f"bad kind: {kind}")
    item_id = uuid.uuid4().hex
    now_ms = int(time.time() * 1000)

    # Ensure directories exist (also via _conn but be safe for direct calls).
    APP_DIR.mkdir(parents=True, exist_ok=True)
    GALLERY_DIR.mkdir(exist_ok=True)
    GALLERY_THUMBS.mkdir(exist_ok=True)

    file_path = GALLERY_DIR / f"{item_id}.png"
    thumb_path = GALLERY_THUMBS / f"{item_id}.jpg"
    file_path.write_bytes(png_bytes)
    width, height = _make_thumb(png_bytes, thumb_path)

    if not name:
        ts = time.strftime("%m-%d %H:%M:%S", time.localtime(now_ms / 1000))
        kind_cn = "原图" if kind == "raw" else "译图"
        lang = f" {src_lang}→{tgt_lang}" if src_lang and tgt_lang else ""
        name = f"{kind_cn}{lang} {ts}"

    with _conn() as c:
        c.executescript(_SCHEMA)
        c.execute(
            "INSERT INTO gallery_items(id,name,kind,src_lang,tgt_lang,file_path,thumb_path,"
            "width,height,canvas_x,canvas_y,canvas_scale,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,0,0,1,?)",
            (item_id, name, kind, src_lang, tgt_lang,
             str(file_path), str(thumb_path), width, height, now_ms),
        )
    return GalleryItem(item_id, name, kind, src_lang, tgt_lang,
                      str(file_path), str(thumb_path),
                      width, height, 0.0, 0.0, 1.0, now_ms)


def list_gallery_items() -> list[GalleryItem]:
    with _conn() as c:
        c.executescript(_SCHEMA)
        rows = c.execute(
            "SELECT id,name,kind,src_lang,tgt_lang,file_path,thumb_path,"
            "width,height,canvas_x,canvas_y,canvas_scale,created_at "
            "FROM gallery_items ORDER BY created_at DESC"
        ).fetchall()
    return [GalleryItem(*r) for r in rows]


def update_gallery_pos(item_id: str, x: float, y: float, scale: float | None = None) -> None:
    with _conn() as c:
        if scale is None:
            c.execute("UPDATE gallery_items SET canvas_x=?, canvas_y=? WHERE id=?",
                      (x, y, item_id))
        else:
            c.execute("UPDATE gallery_items SET canvas_x=?, canvas_y=?, canvas_scale=? WHERE id=?",
                      (x, y, scale, item_id))


def rename_gallery_item(item_id: str, name: str) -> None:
    name = (name or "").strip()
    if not name:
        return
    with _conn() as c:
        c.execute("UPDATE gallery_items SET name=? WHERE id=?", (name, item_id))


def delete_gallery_item(item_id: str) -> None:
    with _conn() as c:
        row = c.execute(
            "SELECT file_path, thumb_path FROM gallery_items WHERE id=?",
            (item_id,)
        ).fetchone()
        c.execute("DELETE FROM gallery_items WHERE id=?", (item_id,))
    if row:
        for p in row:
            if p:
                try:
                    Path(p).unlink(missing_ok=True)
                except OSError:
                    pass


def delete_shot(shot_id: str) -> None:
    with _conn() as c:
        row = c.execute("SELECT orig_path, export_path FROM shots WHERE id=?", (shot_id,)).fetchone()
        c.execute("DELETE FROM shots WHERE id=?", (shot_id,))
    if row:
        for p in row:
            if p:
                try:
                    Path(p).unlink(missing_ok=True)
                except OSError:
                    pass
