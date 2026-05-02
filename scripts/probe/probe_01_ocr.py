"""
Probe #1: Vision framework OCR 精度 & 性能
跑 samples/ 里的 5 张图，打印识别文本 + bbox + 耗时。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import Vision
import Quartz
from Foundation import NSURL

SAMPLES = Path(__file__).parent / "samples"


def ocr(image_path: Path, langs=("zh-Hans", "en-US", "ja")):
    url = NSURL.fileURLWithPath_(str(image_path))
    src = Quartz.CGImageSourceCreateWithURL(url, None)
    cg_image = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)
    w = Quartz.CGImageGetWidth(cg_image)
    h = Quartz.CGImageGetHeight(cg_image)

    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg_image, None)
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    req.setUsesLanguageCorrection_(True)
    req.setRecognitionLanguages_(list(langs))

    t0 = time.perf_counter()
    ok, err = handler.performRequests_error_([req], None)
    dt = time.perf_counter() - t0
    if not ok:
        print(f"  [ERR] {err}")
        return dt, []

    blocks = []
    for obs in req.results() or []:
        top = obs.topCandidates_(1)
        if not top:
            continue
        cand = top[0]
        text = cand.string()
        conf = float(cand.confidence())
        bb = obs.boundingBox()
        # Vision: origin bottom-left, normalized 0-1.
        x = bb.origin.x
        y_bl = bb.origin.y
        bw = bb.size.width
        bh = bb.size.height
        # Convert to top-left origin normalized.
        y = 1.0 - (y_bl + bh)
        blocks.append((text, conf, (x, y, bw, bh)))
    return dt, blocks, (w, h)


def main():
    files = sorted(SAMPLES.glob("*.png"))
    if not files:
        print("no samples")
        sys.exit(1)

    for f in files:
        result = ocr(f)
        dt, blocks, (w, h) = result
        print(f"\n=== {f.name}  {w}x{h}  OCR {dt*1000:.0f}ms  blocks={len(blocks)} ===")
        for text, conf, bbox in blocks:
            x, y, bw, bh = bbox
            px = int(x * w)
            py = int(y * h)
            pw = int(bw * w)
            ph = int(bh * h)
            text_disp = text if len(text) <= 60 else text[:57] + "..."
            print(f"  [{conf:.2f}] ({px:4d},{py:4d} {pw:3d}x{ph:2d})  {text_disp}")


if __name__ == "__main__":
    main()
