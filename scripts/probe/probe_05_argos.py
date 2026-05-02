"""
Probe #5: argos 多段翻译吞吐 (串行 vs 线程并发)。
"""
from __future__ import annotations

import time
import warnings
from concurrent.futures import ThreadPoolExecutor

warnings.filterwarnings("ignore")

import argostranslate.translate as at

PARAGRAPHS_EN_ZH = [
    "We are currently investigating this issue.",
    "Download the React DevTools for a better development experience.",
    "The issue has been identified and a fix is being implemented.",
    "Select a condition.",
    "Copyright 2026 Apple Inc. All rights reserved.",
    "Elevated connection reset errors in Cowork.",
    "Update - We are continuing to investigate this issue.",
    "Service worker registration successful with scope.",
    "Proxy Call Failed with error 500 internal server error.",
    "Open Recent Logs and view the console output.",
]


def get_fn(src, tgt):
    langs = at.get_installed_languages()
    src_l = next(l for l in langs if l.code == src)
    tgt_l = next(l for l in langs if l.code == tgt)
    tr = src_l.get_translation(tgt_l)
    return tr.translate


def run_serial(fn, texts):
    t0 = time.perf_counter()
    out = [fn(t) for t in texts]
    return time.perf_counter() - t0, out


def run_parallel(fn, texts, workers=4):
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        out = list(ex.map(fn, texts))
    return time.perf_counter() - t0, out


def main():
    fn = get_fn("en", "zh")
    # warmup
    fn("hello world")

    print(f"\n=== en→zh  {len(PARAGRAPHS_EN_ZH)} paragraphs ===")
    dt_s, out_s = run_serial(fn, PARAGRAPHS_EN_ZH)
    print(f"serial:    {dt_s*1000:.0f}ms  ({dt_s/len(PARAGRAPHS_EN_ZH)*1000:.0f}ms/item)")
    for inp, op in zip(PARAGRAPHS_EN_ZH[:3], out_s[:3]):
        print(f"  {inp[:40]:<40} → {op[:40]}")

    for w in (2, 4, 8):
        dt_p, out_p = run_parallel(fn, PARAGRAPHS_EN_ZH, workers=w)
        print(f"parallel{w}: {dt_p*1000:.0f}ms  (speedup {dt_s/dt_p:.2f}x)")


if __name__ == "__main__":
    main()
