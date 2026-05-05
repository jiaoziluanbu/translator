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
  pinned       INTEGER NOT NULL DEFAULT 0,    -- 1 if user manually positioned
  group_id     TEXT,                          -- nullable; FK to gallery_groups.id
  created_at   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gallery_created ON gallery_items(created_at DESC);
CREATE TABLE IF NOT EXISTS gallery_groups (
  id           TEXT PRIMARY KEY,
  name         TEXT NOT NULL,
  canvas_x     REAL NOT NULL DEFAULT 0,
  canvas_y     REAL NOT NULL DEFAULT 0,
  pinned       INTEGER NOT NULL DEFAULT 0,
  created_at   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_groups_created ON gallery_groups(created_at DESC);
"""


def _migrate_v2_1(c: sqlite3.Connection) -> None:
    """Add pinned + group_id columns to gallery_items if missing.

    Pre-v2.1 rows have canvas_x/y reflecting user drags (or 0,0 default).
    Treat any row with non-zero coords as pinned=1 so existing manual
    layouts survive the upgrade.
    """
    cols = {row[1] for row in c.execute("PRAGMA table_info(gallery_items)").fetchall()}
    if "pinned" not in cols:
        c.execute("ALTER TABLE gallery_items ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")
        c.execute(
            "UPDATE gallery_items SET pinned=1 "
            "WHERE canvas_x != 0 OR canvas_y != 0"
        )
    if "group_id" not in cols:
        c.execute("ALTER TABLE gallery_items ADD COLUMN group_id TEXT")
    c.execute("CREATE INDEX IF NOT EXISTS idx_gallery_group ON gallery_items(group_id)")


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
    c.executescript(_SCHEMA)
    _migrate_v2_1(c)
    return c


def init_db() -> None:
    with _conn() as c:
        c.executescript(_SCHEMA)
        _migrate_v2_1(c)


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
    pinned: int = 0
    group_id: str | None = None


@dataclass
class GalleryGroup:
    id: str
    name: str
    canvas_x: float
    canvas_y: float
    pinned: int
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
        c.execute(
            "INSERT INTO gallery_items(id,name,kind,src_lang,tgt_lang,file_path,thumb_path,"
            "width,height,canvas_x,canvas_y,canvas_scale,pinned,group_id,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,0,0,1,0,NULL,?)",
            (item_id, name, kind, src_lang, tgt_lang,
             str(file_path), str(thumb_path), width, height, now_ms),
        )
    return GalleryItem(item_id, name, kind, src_lang, tgt_lang,
                      str(file_path), str(thumb_path),
                      width, height, 0.0, 0.0, 1.0, now_ms, 0, None)


def list_gallery_items() -> list[GalleryItem]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id,name,kind,src_lang,tgt_lang,file_path,thumb_path,"
            "width,height,canvas_x,canvas_y,canvas_scale,created_at,pinned,group_id "
            "FROM gallery_items ORDER BY created_at DESC"
        ).fetchall()
    return [GalleryItem(*r) for r in rows]


def list_gallery_groups() -> list[GalleryGroup]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id,name,canvas_x,canvas_y,pinned,created_at "
            "FROM gallery_groups ORDER BY created_at DESC"
        ).fetchall()
    return [GalleryGroup(*r) for r in rows]


def update_gallery_pos(item_id: str, x: float, y: float, scale: float | None = None,
                       pinned: bool | None = None) -> None:
    """Update item position (and optionally scale, pinned flag).

    The gallery now snaps to a grid, so any explicit position write should
    also flip pinned=1 unless the caller passes pinned=False (only auto-
    layout code path passes False)."""
    with _conn() as c:
        sets = ["canvas_x=?", "canvas_y=?"]
        args: list = [x, y]
        if scale is not None:
            sets.append("canvas_scale=?")
            args.append(scale)
        if pinned is None:
            sets.append("pinned=1")
        else:
            sets.append("pinned=?")
            args.append(1 if pinned else 0)
        args.append(item_id)
        c.execute(f"UPDATE gallery_items SET {','.join(sets)} WHERE id=?", args)


def update_gallery_auto_pos(item_id: str, x: float, y: float) -> None:
    """Position writeback for auto-layout flow — does NOT flip pinned."""
    with _conn() as c:
        c.execute(
            "UPDATE gallery_items SET canvas_x=?, canvas_y=? "
            "WHERE id=? AND pinned=0",
            (x, y, item_id),
        )


def set_gallery_pinned(item_id: str, pinned: bool) -> None:
    with _conn() as c:
        c.execute("UPDATE gallery_items SET pinned=? WHERE id=?",
                  (1 if pinned else 0, item_id))


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


# ---------- gallery groups ----------

def create_gallery_group(item_ids: list[str], *, name: str | None = None,
                        canvas_x: float = 0.0, canvas_y: float = 0.0,
                        pinned: bool = False) -> str:
    """Create a new group and assign all given items into it.

    Returns the new group_id. Any prior group membership of these items
    is replaced (each item belongs to at most one group)."""
    if not item_ids:
        raise ValueError("group must have at least 1 item")
    group_id = uuid.uuid4().hex
    now_ms = int(time.time() * 1000)
    if not name:
        name = f"分组 {time.strftime('%m-%d %H:%M', time.localtime(now_ms / 1000))}"
    with _conn() as c:
        c.execute(
            "INSERT INTO gallery_groups(id,name,canvas_x,canvas_y,pinned,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (group_id, name, canvas_x, canvas_y, 1 if pinned else 0, now_ms),
        )
        for iid in item_ids:
            c.execute(
                "UPDATE gallery_items SET group_id=? WHERE id=?",
                (group_id, iid),
            )
    return group_id


def update_group_pos(group_id: str, x: float, y: float,
                     pinned: bool | None = None) -> None:
    with _conn() as c:
        if pinned is None:
            c.execute(
                "UPDATE gallery_groups SET canvas_x=?, canvas_y=?, pinned=1 WHERE id=?",
                (x, y, group_id),
            )
        else:
            c.execute(
                "UPDATE gallery_groups SET canvas_x=?, canvas_y=?, pinned=? WHERE id=?",
                (x, y, 1 if pinned else 0, group_id),
            )


def update_group_auto_pos(group_id: str, x: float, y: float) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE gallery_groups SET canvas_x=?, canvas_y=? "
            "WHERE id=? AND pinned=0",
            (x, y, group_id),
        )


def rename_gallery_group(group_id: str, name: str) -> None:
    name = (name or "").strip()
    if not name:
        return
    with _conn() as c:
        c.execute("UPDATE gallery_groups SET name=? WHERE id=?", (name, group_id))


def add_to_group(item_id: str, group_id: str) -> None:
    with _conn() as c:
        c.execute("UPDATE gallery_items SET group_id=? WHERE id=?",
                  (group_id, item_id))


def remove_from_group(item_id: str) -> None:
    """Move item back to ungrouped state."""
    with _conn() as c:
        c.execute("UPDATE gallery_items SET group_id=NULL WHERE id=?", (item_id,))


def dissolve_group(group_id: str) -> None:
    """Remove the group container; items return to ungrouped state."""
    with _conn() as c:
        c.execute("UPDATE gallery_items SET group_id=NULL WHERE group_id=?",
                  (group_id,))
        c.execute("DELETE FROM gallery_groups WHERE id=?", (group_id,))


def delete_group_with_items(group_id: str) -> None:
    """Delete the group and all its items (files included)."""
    with _conn() as c:
        rows = c.execute(
            "SELECT file_path, thumb_path FROM gallery_items WHERE group_id=?",
            (group_id,),
        ).fetchall()
        c.execute("DELETE FROM gallery_items WHERE group_id=?", (group_id,))
        c.execute("DELETE FROM gallery_groups WHERE id=?", (group_id,))
    for row in rows:
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
