"""Screenshot → OCR → translate → align pipeline.

Glues `ui.capture`, `core.ocr`, `core.translate`, and `core.layout` so the
daemon / editor window can call one entry point per capture.

Task #4 of v1.1: OCR integration into the screenshot flow.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from . import ocr as ocr_mod
from . import translate as tr_mod
from . import layout as layout_mod
from .ocr import TextBlock
from .layout import AlignedBlock


@dataclass
class CaptureOCRResult:
    png_bytes: bytes
    x: int          # pixel rect on main display (top-left origin)
    y: int
    w: int
    h: int
    img_w: int      # captured image pixel size (= w, h in most cases)
    img_h: int
    src_lang: str
    tgt_lang: str
    blocks: list[TextBlock] = field(default_factory=list)
    translations: list[str] = field(default_factory=list)
    aligned: list[AlignedBlock] = field(default_factory=list)


def run_ocr_translate(
    png_bytes: bytes,
    *,
    tgt_lang: str = "zh",
    src_lang: Optional[str] = None,
    min_confidence: float = 0.3,
) -> tuple[list[TextBlock], list[str], list[AlignedBlock], str]:
    """Run OCR then translate each visual module as one unit.

    Blocks are clustered in 2D (see layout.cluster_modules) so multi-column
    layouts don't get smeared across columns. Each cluster's joined text is
    sent to the translator once — this gives better context than per-block
    translation and keeps the right-side column aligned to modules.

    Returns (blocks, per_block_translations, aligned_modules, src_lang).
    `per_block_translations` is kept for backward compat (storage expects one
    row per block); each block's translation is the module's translation.
    """
    blocks = ocr_mod.ocr(png_bytes, min_confidence=min_confidence)
    if not blocks:
        return [], [], [], src_lang or "en"

    if src_lang is None:
        src_lang = tr_mod.detect_lang(blocks[0].text)

    def _translate(text: str) -> str:
        if not text.strip():
            return ""
        try:
            return tr_mod.translate(text, src_lang, tgt_lang)
        except tr_mod.TranslateError:
            return ""

    aligned = layout_mod.align_modules(blocks, _translate)

    # Map each block to its module's translation so storage rows stay 1:1.
    clusters = layout_mod.cluster_modules(blocks)
    tgt_by_cluster = [a.tgt_text for a in aligned]
    translations: list[str] = [""] * len(blocks)
    idx_of = {id(b): i for i, b in enumerate(blocks)}
    for c, tgt in zip(clusters, tgt_by_cluster):
        for b in c:
            translations[idx_of[id(b)]] = tgt

    return blocks, translations, aligned, src_lang


def capture_and_translate(
    *,
    tgt_lang: str = "zh",
    src_lang: Optional[str] = None,
) -> Optional[CaptureOCRResult]:
    """Show overlay, capture region, run OCR + translate. None if cancelled."""
    # Imported lazily so non-capture callers (tests, headless) can import
    # this module without pulling in AppKit overlay code.
    from ui.capture import capture_region

    cap = capture_region()
    if cap is None:
        return None

    # Image pixel size equals the captured rect in pixels for Retina displays.
    img_w, img_h = cap.w, cap.h

    blocks, translations, aligned, src_lang = run_ocr_translate(
        cap.png_bytes, tgt_lang=tgt_lang, src_lang=src_lang
    )

    return CaptureOCRResult(
        png_bytes=cap.png_bytes,
        x=cap.x, y=cap.y, w=cap.w, h=cap.h,
        img_w=img_w, img_h=img_h,
        src_lang=src_lang, tgt_lang=tgt_lang,
        blocks=blocks, translations=translations, aligned=aligned,
    )


def persist_result(result: CaptureOCRResult) -> str:
    """Save `result` via core.storage; returns shot_id."""
    from . import storage
    storage.init_db()
    rows = [{
        "bbox_x": b.x, "bbox_y": b.y, "bbox_w": b.w, "bbox_h": b.h,
        "src_text": b.text, "tgt_text": t, "confidence": b.confidence,
    } for b, t in zip(result.blocks, result.translations)]
    return storage.save_shot(
        result.png_bytes, rows, result.src_lang, result.tgt_lang,
        result.img_w, result.img_h,
    )
