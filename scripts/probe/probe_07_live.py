"""Live end-to-end: overlay → capture → OCR → translate.

Prints paragraphs and saves the captured PNG to ~/Desktop so you can
eyeball the bbox/text quality.
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core import pipeline


def main():
    print("Drag a region with text on screen. ESC to cancel.", flush=True)
    r = pipeline.capture_and_translate(tgt_lang="zh")
    if r is None:
        print("[cancelled]")
        return
    out = Path.home() / "Desktop" / "pipeline_live.png"
    out.write_bytes(r.png_bytes)
    print(f"saved {out}  rect=({r.x},{r.y},{r.w},{r.h})")
    print(f"src_lang={r.src_lang} blocks={len(r.blocks)} paragraphs={len(r.aligned)}")
    for i, a in enumerate(r.aligned):
        print(f"  [{i}] y={a.y_top} h={a.height}")
        print(f"      src: {a.src_text[:80]}")
        print(f"      tgt: {a.tgt_text[:80]}")


if __name__ == "__main__":
    main()
