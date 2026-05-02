"""Text-block layout: cluster OCR blocks into visual modules (2D) and align
them to the right-side translation column.

Each cluster corresponds to a "visual module" in the screenshot — a card, a
paragraph, a header group — so the translation on the right lines up with
the module rather than getting smeared across columns.
"""
from __future__ import annotations

from dataclasses import dataclass

from .ocr import TextBlock


@dataclass
class AlignedBlock:
    src_text: str
    tgt_text: str
    y_top: int       # pixel y of the module's top edge in the original image
    height: int      # module pixel height
    x_left: int = 0  # module left edge (for diagnostics / future column logic)
    width: int = 0


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return 0.0
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def cluster_modules(blocks: list[TextBlock],
                    y_gap_ratio: float = 0.9,
                    x_gap_ratio: float = 1.8) -> list[list[TextBlock]]:
    """Cluster blocks into visual modules via union-find on 2D proximity.

    Two blocks are merged if either:
      * they share an x-range (same column) AND vertical gap < y_gap_ratio * median_h
      * they share a y-range (same line) AND horizontal gap < x_gap_ratio * median_h

    This keeps multi-column layouts (cards side-by-side) from being merged
    across columns while still grouping wrapped lines of the same paragraph.
    """
    if not blocks:
        return []

    heights = [b.h for b in blocks if b.h > 0]
    median_h = _median(heights) or 1.0
    y_thresh = median_h * y_gap_ratio
    x_thresh = median_h * x_gap_ratio

    n = len(blocks)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    for i in range(n):
        a = blocks[i]
        a_r, a_b = a.x + a.w, a.y + a.h
        for j in range(i + 1, n):
            b = blocks[j]
            b_r, b_b = b.x + b.w, b.y + b.h
            x_overlap = min(a_r, b_r) - max(a.x, b.x)
            y_overlap = min(a_b, b_b) - max(a.y, b.y)
            v_gap = max(0, -y_overlap)
            h_gap = max(0, -x_overlap)
            # Same column: horizontally overlapping, vertically close.
            if x_overlap > 0 and v_gap < y_thresh:
                union(i, j)
            # Same line continuation: vertically overlapping, horizontally close.
            elif y_overlap > 0 and h_gap < x_thresh:
                union(i, j)

    groups: dict[int, list[TextBlock]] = {}
    for idx, b in enumerate(blocks):
        groups.setdefault(find(idx), []).append(b)

    out = list(groups.values())
    # Sort groups by top then left; sort blocks within each group top→bottom, left→right.
    for g in out:
        g.sort(key=lambda b: (b.y, b.x))
    out.sort(key=lambda g: (min(b.y for b in g), min(b.x for b in g)))
    return out


def join_cluster_text(cluster: list[TextBlock], line_merge_ratio: float = 0.5) -> str:
    """Join a cluster's blocks into one string.

    Blocks on the same visual line (y-overlap > line_merge_ratio * min_h) are
    joined with a space; lines are separated by newlines. Preserves reading
    order left→right, top→bottom.
    """
    if not cluster:
        return ""
    # Group into rows.
    rows: list[list[TextBlock]] = []
    for b in sorted(cluster, key=lambda x: (x.y, x.x)):
        placed = False
        for row in rows:
            ref = row[-1]
            y_overlap = min(ref.y + ref.h, b.y + b.h) - max(ref.y, b.y)
            min_h = min(ref.h, b.h) or 1
            if y_overlap > min_h * line_merge_ratio:
                row.append(b)
                placed = True
                break
        if not placed:
            rows.append([b])
    for row in rows:
        row.sort(key=lambda x: x.x)
    return "\n".join(" ".join(b.text for b in row) for row in rows)


def _flatten_for_translate(src: str) -> str:
    """Collapse intra-module newlines to spaces before sending to the engine.

    OCR visual line breaks often fall mid-sentence ("interfaces that leverage
    \\nLiquid Glass"); argos treats \\n as a sentence boundary and loses
    context, producing word-salad translations. We keep the newlines in the
    stored `src_text` for UI display but flatten the version we translate.
    """
    import re
    return re.sub(r"\s+", " ", src).strip()


def align_modules(blocks: list[TextBlock], translate_fn) -> list[AlignedBlock]:
    """Cluster `blocks` into modules and translate each module as one unit.

    `translate_fn(str) -> str` lets callers inject their own translator so
    this module stays dependency-free.
    """
    clusters = cluster_modules(blocks)
    aligned: list[AlignedBlock] = []
    for c in clusters:
        src = join_cluster_text(c)
        try:
            tgt = translate_fn(_flatten_for_translate(src))
        except Exception:
            tgt = ""
        y_top = min(b.y for b in c)
        y_bot = max(b.y + b.h for b in c)
        x_left = min(b.x for b in c)
        x_right = max(b.x + b.w for b in c)
        aligned.append(AlignedBlock(
            src_text=src, tgt_text=tgt,
            y_top=y_top, height=y_bot - y_top,
            x_left=x_left, width=x_right - x_left,
        ))
    return aligned


# --- Backwards-compat shims (older smoke scripts / pipeline still call these) ---

def cluster_paragraphs(blocks: list[TextBlock], line_gap_ratio: float = 0.6) -> list[list[TextBlock]]:
    """Legacy name → now delegates to 2D clustering."""
    return cluster_modules(blocks)


def align_blocks(blocks: list[TextBlock], translations: list[str]) -> list[AlignedBlock]:
    """Legacy API: takes pre-translated per-block strings. Kept for probe_06.

    Clusters 2D, then within each cluster concatenates the matching
    translations in reading order. Prefer `align_modules` for new code.
    """
    if len(translations) != len(blocks):
        raise ValueError("translations length mismatch")
    idx_by_id = {id(b): i for i, b in enumerate(blocks)}
    clusters = cluster_modules(blocks)
    aligned: list[AlignedBlock] = []
    for c in clusters:
        src = join_cluster_text(c)
        tgt = "\n".join(translations[idx_by_id[id(b)]] for b in c)
        y_top = min(b.y for b in c)
        y_bot = max(b.y + b.h for b in c)
        x_left = min(b.x for b in c)
        x_right = max(b.x + b.w for b in c)
        aligned.append(AlignedBlock(
            src_text=src, tgt_text=tgt,
            y_top=y_top, height=y_bot - y_top,
            x_left=x_left, width=x_right - x_left,
        ))
    return aligned
