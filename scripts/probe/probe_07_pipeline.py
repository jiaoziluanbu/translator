"""Task #4 smoke: run the capture→OCR→translate pipeline on a saved sample.

Bypasses the interactive overlay by feeding PNG bytes directly into
`core.pipeline.run_ocr_translate`. The live `capture_and_translate` is
exercised manually via daemon hotkey once the editor lands.
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core import pipeline

SAMPLE = Path(__file__).parent / "samples" / "03-en-web.png"


def main():
    png = SAMPLE.read_bytes()
    blocks, translations, aligned, src = pipeline.run_ocr_translate(png, tgt_lang="zh")
    print(f"sample={SAMPLE.name} src_lang={src}")
    print(f"blocks={len(blocks)} paragraphs={len(aligned)}")
    for i, a in enumerate(aligned[:3]):
        print(f"  [{i}] y={a.y_top} h={a.height}")
        print(f"      src: {a.src_text[:70]}")
        print(f"      tgt: {a.tgt_text[:70]}")
    assert len(translations) == len(blocks)
    print("OK pipeline smoke passed")


if __name__ == "__main__":
    main()
