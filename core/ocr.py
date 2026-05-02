"""Vision framework OCR wrapper.

Returns TextBlock list with pixel coordinates (top-left origin).
Coordinate convention matches PIL / common image-editing tools.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import Vision
import Quartz
from Foundation import NSURL, NSData


@dataclass
class TextBlock:
    text: str
    x: int  # pixel, top-left origin
    y: int
    w: int
    h: int
    confidence: float


_DEFAULT_LANGS = ("zh-Hans", "en-US", "ja")


def _cg_image_from_bytes(png_bytes: bytes):
    data = NSData.dataWithBytes_length_(png_bytes, len(png_bytes))
    src = Quartz.CGImageSourceCreateWithData(data, None)
    if src is None:
        raise ValueError("cannot decode image bytes")
    return Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)


def _cg_image_from_path(path: Path):
    url = NSURL.fileURLWithPath_(str(path))
    src = Quartz.CGImageSourceCreateWithURL(url, None)
    if src is None:
        raise FileNotFoundError(path)
    return Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)


def ocr(image: bytes | str | Path, langs: tuple[str, ...] = _DEFAULT_LANGS,
        min_confidence: float = 0.3) -> list[TextBlock]:
    """Run Vision OCR. Accepts PNG/JPEG bytes or file path."""
    if isinstance(image, (str, Path)):
        cg = _cg_image_from_path(Path(image))
    else:
        cg = _cg_image_from_bytes(image)

    w = Quartz.CGImageGetWidth(cg)
    h = Quartz.CGImageGetHeight(cg)

    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg, None)
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    req.setUsesLanguageCorrection_(True)
    req.setRecognitionLanguages_(list(langs))

    ok, err = handler.performRequests_error_([req], None)
    if not ok:
        raise RuntimeError(f"Vision OCR failed: {err}")

    blocks: list[TextBlock] = []
    for obs in req.results() or []:
        top = obs.topCandidates_(1)
        if not top:
            continue
        cand = top[0]
        conf = float(cand.confidence())
        if conf < min_confidence:
            continue
        bb = obs.boundingBox()
        # Vision: origin bottom-left, normalized 0-1.
        x_norm = bb.origin.x
        bw = bb.size.width
        bh = bb.size.height
        y_top_norm = 1.0 - (bb.origin.y + bh)
        blocks.append(TextBlock(
            text=cand.string(),
            x=int(x_norm * w),
            y=int(y_top_norm * h),
            w=int(bw * w),
            h=int(bh * h),
            confidence=conf,
        ))
    # Sort top-to-bottom, left-to-right.
    blocks.sort(key=lambda b: (b.y, b.x))
    return blocks
