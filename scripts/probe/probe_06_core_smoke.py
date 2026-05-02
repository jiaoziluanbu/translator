"""End-to-end smoke: ocr + translate + layout + storage.

Runs OCR on one sample, translates each block, persists to a temp DB,
reads it back, and prints aligned paragraphs.
"""
from __future__ import annotations

import os
import sys
import tempfile
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core import ocr as ocr_mod
from core import translate as tr_mod
from core import layout as layout_mod
from core import storage


# Redirect app data dir to a temp path so we don't pollute ~/Library.
tmp = Path(tempfile.mkdtemp(prefix="translator_probe_"))
storage.APP_DIR = tmp
storage.SHOTS_DIR = tmp / "shots"
storage.EXPORTS_DIR = tmp / "exports"
storage.DB_PATH = tmp / "db.sqlite"

SAMPLE = Path(__file__).parent / "samples" / "03-en-web.png"


def main():
    print(f"Sample: {SAMPLE.name}  tmp={tmp}")
    blocks = ocr_mod.ocr(SAMPLE)
    print(f"OCR: {len(blocks)} blocks")
    if not blocks:
        return

    # Translate each block to Chinese.
    src_lang = tr_mod.detect_lang(blocks[0].text)
    print(f"detected src_lang={src_lang}")
    translations = [tr_mod.translate(b.text, src_lang, "zh") for b in blocks]

    # Paragraph clustering.
    aligned = layout_mod.align_blocks(blocks, translations)
    print(f"paragraphs: {len(aligned)}")
    for i, a in enumerate(aligned[:5]):
        print(f"  [{i}] y={a.y_top} h={a.height}")
        print(f"      src: {a.src_text[:60]}")
        print(f"      tgt: {a.tgt_text[:60]}")

    # Persist.
    storage.init_db()
    png_bytes = SAMPLE.read_bytes()
    rows = [{
        "bbox_x": b.x, "bbox_y": b.y, "bbox_w": b.w, "bbox_h": b.h,
        "src_text": b.text, "tgt_text": t, "confidence": b.confidence,
    } for b, t in zip(blocks, translations)]
    # Read image size via Quartz for convenience:
    import Quartz
    from Foundation import NSURL
    u = NSURL.fileURLWithPath_(str(SAMPLE))
    src = Quartz.CGImageSourceCreateWithURL(u, None)
    img = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)
    w = Quartz.CGImageGetWidth(img)
    h = Quartz.CGImageGetHeight(img)

    shot_id = storage.save_shot(png_bytes, rows, src_lang, "zh", w, h)
    print(f"saved shot {shot_id}")

    # Read back.
    shots = storage.list_shots()
    print(f"list_shots: {len(shots)}  (latest id={shots[0].id[:8]}  {shots[0].width}x{shots[0].height})")
    assert shots[0].id == shot_id
    print("OK smoke passed")


if __name__ == "__main__":
    main()
