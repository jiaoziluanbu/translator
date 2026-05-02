"""Editor window (v1.1 skeleton): image on the left, 320px translation column on the right.

No toolbar yet. Loads `editor.html`, injects payload via a generated wrapper
HTML so Konva + the image + aligned paragraphs render on first paint.

Key decisions (from workspace):
  - Image is passed via file:// (base64 is 4x slower on 1.5MB+ images).
  - Window width = scaled_img_w + 320. If img_w + 320 exceeds 85% of screen
    width, we scale the image down; the sidebar y positions scale along.
  - Height behaves the same way against screen height.
"""
from __future__ import annotations

# --- Boot timing log (write before any heavy imports) ---
import os as _os, sys as _sys, time as _time
_BOOT_T0 = _time.time()
def _boot_log(msg):
    try:
        with open("/tmp/translator-editor.log", "a", encoding="utf-8") as f:
            f.write(f"[{_time.strftime('%H:%M:%S')}] +{(_time.time() - _BOOT_T0):.2f}s pid={_os.getpid()} {msg}\n")
    except Exception:
        pass
_boot_log(f"editor boot start argv={_sys.argv}")

import base64
import json
import os
import sys
import tempfile
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Optional

# Allow running as a script (`python3 ui/editor_window.py`) from anywhere;
# inside py2app bundle RESOURCEPATH replaces the source-root resolution.
_PROJECT_ROOT = Path(os.environ.get("RESOURCEPATH") or Path(__file__).resolve().parents[1])
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_boot_log("importing pywebview")
import webview
_boot_log("pywebview imported")

# IMPORTANT: do NOT do `from core.pipeline import CaptureOCRResult` at module
# top — that drags in core.ocr (Vision bridge) + core.translate (the whole
# torch + argostranslate + swift-helper stack), adding 5-8s of cold-start to
# the editor process. Under --from-image we don't need any of it. Use a
# string-typed alias for type hints and lazy-import the real class only in
# the legacy --from-result / --from-meta / --sample paths below.
CaptureOCRResult = "CaptureOCRResult"  # placeholder; type hint only

SIDEBAR_W = 320
# Minimum editor window width — needs to fit the toolbar without truncation:
# 11 tool buttons + color/stroke/font groups + 3 left actions + flex spacer
# + 3 right actions ≈ 1300px. The canvas-wrap flex-grows to fill the extra
# horizontal space when the screenshot is narrower than (window − sidebar).
MIN_WIN_W = 1300
MIN_WIN_H = 600
_HERE = _PROJECT_ROOT / "ui"
_EDITOR_HTML = _HERE / "editor.html"


def _screen_size() -> tuple[int, int]:
    try:
        from AppKit import NSScreen
        frame = NSScreen.mainScreen().visibleFrame()
        return int(frame.size.width), int(frame.size.height)
    except Exception:
        return 1440, 900


def _compute_scale(img_w: int, img_h: int) -> float:
    sw, sh = _screen_size()
    max_img_w = int(sw * 0.85) - SIDEBAR_W
    max_img_h = int(sh * 0.85)
    if max_img_w <= 100 or max_img_h <= 100:
        return 1.0
    return min(1.0, max_img_w / img_w, max_img_h / img_h)


def _build_payload(result: CaptureOCRResult, image_url: str, scale: float) -> dict:
    return {
        "image_url": image_url,
        "img_w": result.img_w,
        "img_h": result.img_h,
        "scale": scale,
        "src_lang": result.src_lang,
        "tgt_lang": result.tgt_lang,
        "aligned": [asdict(a) for a in result.aligned],
    }


def _write_wrapper_html(payload: dict) -> Path:
    """Write a wrapper HTML that embeds the payload then loads editor.html inline.

    Simpler than post-load injection: avoids timing races where the page-side
    script runs before `window.__EDITOR_PAYLOAD__` is set.

    Also rewrites the relative `vendor/konva.min.js` reference to an absolute
    file:// URL pointing into the source/bundle so the wrapper (which lives
    in /var/folders/T/lt_editor_*/) can find the script.
    """
    editor_src = _EDITOR_HTML.read_text(encoding="utf-8")
    inject = f"<script>window.__EDITOR_PAYLOAD__ = {json.dumps(payload, ensure_ascii=False)};</script>"
    konva_uri = (_HERE / "vendor" / "konva.min.js").as_uri()
    editor_src = editor_src.replace("vendor/konva.min.js", konva_uri, 1)
    marked = editor_src.replace("</head>", inject + "\n</head>", 1)
    tmp = Path(tempfile.mkdtemp(prefix="lt_editor_")) / "editor.html"
    tmp.write_text(marked, encoding="utf-8")
    return tmp


def _default_save_dir() -> Path:
    # Prefer ~/Downloads; fall back to home if missing.
    d = Path.home() / "Downloads"
    return d if d.exists() else Path.home()


class _EditorApi:
    def __init__(self, src_lang: str = "", tgt_lang: str = ""):
        self.ready_payload: Optional[dict] = None
        self.src_lang = src_lang
        self.tgt_lang = tgt_lang
        # When the editor was opened in pending mode (--from-image), the
        # background watcher thread sets these once OCR+translate finishes.
        # Primary delivery is push (window.evaluate_js → __onTranslationResult);
        # get_translation_result() stays as a one-shot fallback for the race
        # where result lands before JS registers the receiver.
        self._pending_result: Optional[dict] = None
        self._pending_error: Optional[str] = None

    def get_translation_result(self) -> Optional[dict]:
        """Fallback path: JS calls this once after registering its receiver
        in case the result already arrived before push could fire.
          - None: still translating
          - {"ok": True, "src_lang", "tgt_lang", "aligned": [...]}: ready
          - {"ok": False, "error": "..."}: failed (display message in sidebar)
        """
        if self._pending_error is not None:
            return {"ok": False, "error": self._pending_error}
        if self._pending_result is not None:
            return {"ok": True, **self._pending_result}
        return None

    def ready(self, info):
        print(f"[editor] ready: {info}", flush=True)
        try:
            with open("/tmp/translator-editor.log", "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%H:%M:%S')}] ready: {info}\n")
        except Exception:
            pass
        self.ready_payload = info

    def jslog(self, msg: str) -> dict:
        """JS-side logger. Anything the page wants to surface (errors, render
        progress, image load state) gets piped here and written to a log."""
        try:
            with open("/tmp/translator-editor.log", "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        except Exception:
            pass
        return {"ok": True}

    def copy_png(self, b64: str) -> dict:
        """Decode base64 PNG and put it on the macOS clipboard as image data.

        Uses NSPasteboard with NSPasteboardTypePNG so paste targets that
        expect images (Preview, Notes, Messages, Slack, browsers) get the
        image rather than a file reference.
        """
        try:
            data = base64.b64decode(b64)
            from AppKit import NSPasteboard, NSPasteboardTypePNG
            from Foundation import NSData
            pb = NSPasteboard.generalPasteboard()
            pb.clearContents()
            ns_data = NSData.dataWithBytes_length_(data, len(data))
            ok = pb.setData_forType_(ns_data, NSPasteboardTypePNG)
            if not ok:
                return {"ok": False, "error": "NSPasteboard rejected data"}
            print(f"[editor] copied to clipboard ({len(data)} bytes)", flush=True)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def save_to_gallery(self, b64: str, kind: str = "raw") -> dict:
        """Decode PNG and persist into the gallery (DB + Application Support).

        kind: 'raw' (image only) or 'translated' (image + translation column).
        Returns {ok, id, name} or {ok: False, error}.
        """
        try:
            from core import storage
            data = base64.b64decode(b64)
            item = storage.add_gallery_item(
                data, kind,
                src_lang=self.src_lang, tgt_lang=self.tgt_lang,
            )
            print(f"[editor] saved to gallery: {item.id} ({kind}, {len(data)} bytes)", flush=True)
            return {"ok": True, "id": item.id, "name": item.name}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def save_png(self, b64: str, suffix: str = "") -> dict:
        """Decode base64 PNG and write to ~/Downloads/.

        `suffix` (optional) is appended before the timestamp, e.g.
        "with-translation" to distinguish the combined export from the
        image-only one. Returns {ok, path} or {ok: False, error}.
        """
        try:
            data = base64.b64decode(b64)
            ts = time.strftime("%Y%m%d-%H%M%S")
            lang = f"{self.src_lang}-{self.tgt_lang}" if self.src_lang else "shot"
            parts = ["LocalTranslator", lang]
            if suffix:
                parts.append(suffix)
            parts.append(ts)
            out = _default_save_dir() / ("-".join(parts) + ".png")
            out.write_bytes(data)
            print(f"[editor] saved: {out}  ({len(data)} bytes)", flush=True)
            return {"ok": True, "path": str(out)}
        except Exception as e:
            return {"ok": False, "error": str(e)}


def open_editor(result: CaptureOCRResult, *, blocking: bool = True) -> None:
    """Open a pywebview window showing the captured image + translation column.

    When `blocking=True`, this call blocks until the window closes (pywebview
    requirement when called from the main thread).
    """
    # Persist PNG to temp so we can serve via file://.
    tmp_img = Path(tempfile.mkdtemp(prefix="lt_shot_")) / "shot.png"
    tmp_img.write_bytes(result.png_bytes)
    image_url = tmp_img.as_uri()

    scale = _compute_scale(result.img_w, result.img_h)
    payload = _build_payload(result, image_url, scale)
    wrapper = _write_wrapper_html(payload)

    win_w = max(int(round(result.img_w * scale)) + SIDEBAR_W, MIN_WIN_W)
    win_h = max(int(round(result.img_h * scale)), MIN_WIN_H)

    api = _EditorApi(src_lang=result.src_lang, tgt_lang=result.tgt_lang)
    webview.create_window(
        title=f"编辑器 — {result.src_lang} → {result.tgt_lang}",
        url=wrapper.as_uri(),
        js_api=api,
        width=win_w,
        height=win_h,
        resizable=True,
    )
    if blocking:
        webview.start()


def open_editor_pending(
    png_bytes: bytes, x: int, y: int, w: int, h: int,
    result_path: str, *, blocking: bool = True,
) -> None:
    _boot_log("open_editor_pending: start")
    """Open the editor immediately with just the screenshot; right column
    shows a 'translating...' spinner. A background thread polls `result_path`
    for the daemon-worker's OCR+translate output and exposes it via
    `_EditorApi.get_translation_result()` for the JS side to pick up.
    """
    tmp_img = Path(tempfile.mkdtemp(prefix="lt_shot_")) / "shot.png"
    tmp_img.write_bytes(png_bytes)
    image_url = tmp_img.as_uri()

    scale = _compute_scale(w, h)
    payload = {
        "image_url": image_url,
        "img_w": w, "img_h": h,
        "scale": scale,
        "src_lang": "...", "tgt_lang": "zh",
        "aligned": [],
        "pending": True,  # tells editor.html to show spinner + start polling
    }
    wrapper = _write_wrapper_html(payload)

    win_w = max(int(round(w * scale)) + SIDEBAR_W, MIN_WIN_W)
    win_h = max(int(round(h * scale)), MIN_WIN_H)

    api = _EditorApi(src_lang="", tgt_lang="zh")

    # Holder for the pywebview Window instance so the watcher thread can
    # push results via evaluate_js once the result file appears.
    win_holder: dict = {}

    def _push_to_js(payload: dict) -> bool:
        win = win_holder.get("w")
        if win is None:
            return False
        try:
            js = (
                "window.__onTranslationResult && "
                "window.__onTranslationResult(" + json.dumps(payload, ensure_ascii=False) + ");"
            )
            win.evaluate_js(js)
            return True
        except Exception as e:
            _boot_log(f"push: evaluate_js failed: {e}")
            return False

    def _watch():
        # Watch the result file using a short interval (atomic os.replace, so
        # once the path exists the content is complete). On hit, push the
        # payload directly into the page; the api fields stay populated as a
        # fallback for the JS-not-ready race.
        timeout_s = 60
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if os.path.exists(result_path):
                try:
                    with open(result_path, encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    time.sleep(0.05)
                    try:
                        with open(result_path, encoding="utf-8") as f:
                            data = json.load(f)
                    except Exception as e2:
                        api._pending_error = f"读取译文失败: {e2}"
                        _push_to_js({"ok": False, "error": api._pending_error})
                        return
                api.src_lang = data.get("src_lang", "")
                api.tgt_lang = data.get("tgt_lang", "zh")
                payload_out = {
                    "ok": True,
                    "src_lang": api.src_lang,
                    "tgt_lang": api.tgt_lang,
                    "aligned": data.get("aligned", []),
                }
                api._pending_result = {
                    "src_lang": api.src_lang,
                    "tgt_lang": api.tgt_lang,
                    "aligned": data.get("aligned", []),
                }
                # Try push; if window not ready yet, retry briefly (the
                # fallback get_translation_result() also covers this).
                pushed = False
                for _ in range(20):  # up to ~1s
                    if _push_to_js(payload_out):
                        pushed = True
                        break
                    time.sleep(0.05)
                _boot_log(f"watch: result pushed={pushed}, aligned={len(payload_out['aligned'])}")
                try:
                    os.unlink(result_path)
                except Exception:
                    pass
                return
            time.sleep(0.05)
        api._pending_error = "翻译超时"
        _push_to_js({"ok": False, "error": api._pending_error})

    threading.Thread(target=_watch, daemon=True).start()

    _boot_log("open_editor_pending: creating window")
    win = webview.create_window(
        title="编辑器 — 翻译中...",
        url=wrapper.as_uri(),
        js_api=api,
        width=win_w,
        height=win_h,
        resizable=True,
    )
    win_holder["w"] = win
    _boot_log("open_editor_pending: calling webview.start()")
    if blocking:
        webview.start()


if __name__ == "__main__":
    # Live entry: capture → OCR → translate → open editor.
    # Modes:
    #   (default)            full pipeline, including capture overlay
    #   --sample             use a built-in demo image, skip capture
    #   --from-meta <path>   pre-captured PNG + rect; subprocess does OCR+translate
    #   --from-result <path> daemon already did everything; just render
    # The `pipeline` import is deferred — under --from-result we don't need
    # argostranslate/torch at all and skipping the import shaves seconds off
    # the editor's cold start.

    if "--from-image" in sys.argv:
        # Image-only mode: open the editor immediately with the screenshot,
        # then poll a result file the daemon-worker writes when OCR+translate
        # finishes. This is the path the daemon uses for ⌃⌥A — user sees the
        # window ~1s after dragging instead of waiting 3-5s.
        idx = sys.argv.index("--from-image")
        meta_path = sys.argv[idx + 1]
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        png = open(meta["png"], "rb").read()
        try:
            os.unlink(meta["png"]); os.unlink(meta_path)
        except Exception:
            pass
        open_editor_pending(
            png_bytes=png,
            x=meta["x"], y=meta["y"], w=meta["w"], h=meta["h"],
            result_path=meta["result_path"],
        )
        sys.exit(0)
    elif "--from-result" in sys.argv:
        # Daemon ran OCR+translate already — we just render. No heavy imports
        # needed beyond what pywebview already pulls.
        import json
        from core.ocr import TextBlock
        from core.layout import AlignedBlock
        from core.pipeline import CaptureOCRResult  # lazy
        idx = sys.argv.index("--from-result")
        meta_path = sys.argv[idx + 1]
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        png = open(meta["png"], "rb").read()
        try:
            os.unlink(meta["png"]); os.unlink(meta_path)
        except Exception:
            pass
        blocks = [TextBlock(**b) for b in meta["blocks"]]
        aligned = [AlignedBlock(**a) for a in meta["aligned"]]
        result = CaptureOCRResult(
            png_bytes=png, x=meta["x"], y=meta["y"], w=meta["w"], h=meta["h"],
            img_w=meta["w"], img_h=meta["h"],
            src_lang=meta["src_lang"], tgt_lang=meta["tgt_lang"],
            blocks=blocks, translations=meta["translations"], aligned=aligned,
        )
    elif "--from-meta" in sys.argv:
        import json
        from core import pipeline
        from core.pipeline import CaptureOCRResult  # lazy
        idx = sys.argv.index("--from-meta")
        meta_path = sys.argv[idx + 1]
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        png = open(meta["png"], "rb").read()
        # Best-effort cleanup of the temp pair the daemon dropped for us.
        try:
            os.unlink(meta["png"]); os.unlink(meta_path)
        except Exception:
            pass
        blocks, translations, aligned, src_lang = pipeline.run_ocr_translate(png, tgt_lang="zh")
        result = CaptureOCRResult(
            png_bytes=png, x=meta["x"], y=meta["y"], w=meta["w"], h=meta["h"],
            img_w=meta["w"], img_h=meta["h"],
            src_lang=src_lang, tgt_lang="zh",
            blocks=blocks, translations=translations, aligned=aligned,
        )
    elif "--sample" in sys.argv:
        from core import pipeline
        from core.pipeline import CaptureOCRResult  # lazy
        SAMPLE = _PROJECT_ROOT / "scripts" / "probe" / "samples" / "03-en-web.png"
        png = SAMPLE.read_bytes()
        blocks, translations, aligned, src_lang = pipeline.run_ocr_translate(png, tgt_lang="zh")
        import Quartz
        from Foundation import NSURL
        u = NSURL.fileURLWithPath_(str(SAMPLE))
        cgsrc = Quartz.CGImageSourceCreateWithURL(u, None)
        cgimg = Quartz.CGImageSourceCreateImageAtIndex(cgsrc, 0, None)
        w, h = Quartz.CGImageGetWidth(cgimg), Quartz.CGImageGetHeight(cgimg)
        result = CaptureOCRResult(
            png_bytes=png, x=0, y=0, w=w, h=h, img_w=w, img_h=h,
            src_lang=src_lang, tgt_lang="zh",
            blocks=blocks, translations=translations, aligned=aligned,
        )
    else:
        from core import pipeline
        print("拖框选择要翻译的区域（ESC 取消）…", flush=True)
        result = pipeline.capture_and_translate(tgt_lang="zh")
        if result is None:
            print("[已取消]")
            sys.exit(0)
        print(f"OCR {len(result.blocks)} blocks, {len(result.aligned)} paragraphs")

    open_editor(result)
