"""Gallery window — Freeform-style infinite canvas of saved shots.

Loads `gallery.html` inside pywebview and exposes a JS API backed by
`core.storage.gallery_*` for browsing, dragging, renaming, deleting,
and double-click lightbox preview.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

# In a py2app bundle RESOURCEPATH points at <App>.app/Contents/Resources;
# in dev it's just the project root.
_PROJECT_ROOT = Path(os.environ.get("RESOURCEPATH") or Path(__file__).resolve().parents[1])
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import webview

from core import storage

_HERE = _PROJECT_ROOT / "ui"
_GALLERY_HTML = _HERE / "gallery.html"


def _items_payload() -> list[dict]:
    items = storage.list_gallery_items()
    out = []
    for it in items:
        d = asdict(it)
        d["file_url"] = Path(it.file_path).as_uri()
        d["thumb_url"] = Path(it.thumb_path).as_uri()
        out.append(d)
    return out


def _write_wrapper_html(payload: dict) -> Path:
    src = _GALLERY_HTML.read_text(encoding="utf-8")
    inject = f"<script>window.__GALLERY_PAYLOAD__ = {json.dumps(payload, ensure_ascii=False)};</script>"
    marked = src.replace("</head>", inject + "\n</head>", 1)
    tmp = Path(tempfile.mkdtemp(prefix="lt_gallery_")) / "gallery.html"
    tmp.write_text(marked, encoding="utf-8")
    return tmp


class _GalleryApi:
    def list(self) -> list[dict]:
        return _items_payload()

    def update_pos(self, item_id: str, x: float, y: float, scale: float | None = None) -> dict:
        try:
            storage.update_gallery_pos(item_id, float(x), float(y),
                                       None if scale is None else float(scale))
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def rename(self, item_id: str, name: str) -> dict:
        try:
            storage.rename_gallery_item(item_id, name)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def delete(self, item_id: str) -> dict:
        try:
            storage.delete_gallery_item(item_id)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}


_window = None


def open_gallery(*, blocking: bool = True) -> None:
    """Open (or focus) the gallery window."""
    global _window
    payload = {"items": _items_payload()}
    wrapper = _write_wrapper_html(payload)
    api = _GalleryApi()
    _window = webview.create_window(
        title="画廊 — Local Translator",
        url=wrapper.as_uri(),
        js_api=api,
        width=1200,
        height=800,
        resizable=True,
    )
    if blocking:
        webview.start()


if __name__ == "__main__":
    open_gallery()
