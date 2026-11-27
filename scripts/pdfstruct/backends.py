"""Backend-agnostic PDF word/char extraction.

The evaluation image declares several PDF tools, but their exact Python bindings are
unknown, so this module probes a chain of backends and uses the first that yields text
with usable coordinates. Every backend returns the same shape:

    Page = {
        "number": int,            # 1-based
        "width": float, "height": float,
        "words": [Word, ...],     # Word = {text, x0, x1, top, bottom, size, font}
        "has_text": bool,
        "backend": str,
    }

Ordering of the chain is deliberate: pdfplumber exposes char-level font size (needed for
heading detection), pdfminer.six is the next-best fallback, pypdf is a last resort that
still gives line text so a degraded-but-honest result can be produced.
"""
from __future__ import annotations

import io
import subprocess
import tempfile
import os


class BackendUnavailable(RuntimeError):
    pass


# ---------------------------------------------------------------- helpers

def _norm_word(text, x0, x1, top, bottom, size=0.0, font=""):
    return {
        "text": text,
        "x0": round(float(x0), 2),
        "x1": round(float(x1), 2),
        "top": round(float(top), 2),
        "bottom": round(float(bottom), 2),
        "size": round(float(size or 0.0), 2),
        "font": font or "",
    }


# ---------------------------------------------------------------- backends

def _backend_pdfplumber(path):
    import pdfplumber  # noqa: F401

    pages = []
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            words = []
            for w in page.extract_words(
                keep_blank_chars=False,
                use_text_flow=False,
                extra_attrs=["size", "fontname"],
            ):
                words.append(
                    _norm_word(
                        w.get("text", ""),
                        w.get("x0", 0),
                        w.get("x1", 0),
                        w.get("top", 0),
                        w.get("bottom", 0),
                        w.get("size", 0),
                        w.get("fontname", ""),
                    )
                )
            pages.append(
                {
                    "number": i,
                    "width": float(page.width),
                    "height": float(page.height),
                    "words": words,
                    "has_text": bool(words),
                    "backend": "pdfplumber",
                }
            )
    return pages


def _backend_pdfminer(path):
    """Character-level extraction, re-grouped into words.

    pdfminer's own convenient output is line-level, which is useless for table detection
    (it destroys the inter-word gaps that mark column separators), so this backend walks
    LTChar and re-derives words from glyph positions.
    """
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LTTextContainer, LTTextLine, LTChar

    pages = []
    for i, layout in enumerate(extract_pages(path), 1):
        height = float(layout.height)
        width = float(layout.width)
        words = []
        for element in layout:
            if not isinstance(element, LTTextContainer):
                continue
            for line in element:
                if not isinstance(line, LTTextLine):
                    continue
                chars = [c for c in line if isinstance(c, LTChar)]
                groups = []
                cur = []
                prev = None
                for ch in chars:
                    glyph = ch.get_text()
                    if not glyph or glyph.isspace():
                        if cur:
                            groups.append(cur)
                            cur = []
                        prev = None
                        continue
                    if prev is not None:
                        size = float(getattr(ch, "size", 10.0) or 10.0)
                        if (ch.x0 - prev.x1) > max(1.0, 0.22 * size):
                            groups.append(cur)
                            cur = []
                    cur.append(ch)
                    prev = ch
                if cur:
                    groups.append(cur)

                for g in groups:
                    text = "".join(c.get_text() for c in g).strip()
                    if not text:
                        continue
                    x0 = min(float(c.x0) for c in g)
                    x1 = max(float(c.x1) for c in g)
                    y0 = min(float(c.y0) for c in g)
                    y1 = max(float(c.y1) for c in g)
                    first = g[0]
                    words.append(
                        _norm_word(
                            text, x0, x1, height - y1, height - y0,
                            float(getattr(first, "size", 0.0) or 0.0),
                            getattr(first, "fontname", "") or "",
                        )
                    )
        pages.append(
            {
                "number": i,
                "width": width,
                "height": height,
                "words": words,
                "has_text": bool(words),
                "backend": "pdfminer.six",
            }
        )
    return pages


def _backend_pypdf(path):
    from pypdf import PdfReader

    reader = PdfReader(path)
    pages = []
    for i, page in enumerate(reader.pages, 1):
        box = page.mediabox
        width = float(box.width)
        height = float(box.height)
        words = []
        text = page.extract_text() or ""
        # pypdf gives no coordinates: synthesise one word per line, stacked top-down.
        y = 0.0
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            words.append(_norm_word(line, 0.0, width, y, y + 12.0, 10.0, ""))
            y += 14.0
        pages.append(
            {
                "number": i,
                "width": width,
                "height": height,
                "words": words,
                "has_text": bool(words),
                "backend": "pypdf (no coordinates)",
            }
        )
    return pages


def _backend_poppler_bbox(path):
    """pdftotext -bbox-layout from poppler-utils, when the image ships it."""
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "out.html")
        proc = subprocess.run(
            ["pdftotext", "-bbox-layout", path, out],
            capture_output=True,
            timeout=300,
        )
        if proc.returncode != 0 or not os.path.exists(out):
            raise BackendUnavailable("pdftotext failed")
        import re

        html = open(out, encoding="utf-8", errors="replace").read()
        pages = []
        page_blocks = re.findall(r"<page\b[^>]*>(.*?)</page>", html, re.S)
        for i, block in enumerate(page_blocks, 1):
            m = re.search(r'width="([\d.]+)"\s+height="([\d.]+)"', block)
            width = float(m.group(1)) if m else 612.0
            height = float(m.group(2)) if m else 792.0
            words = []
            for wm in re.finditer(
                r'<word\s+xMin="([\d.]+)"\s+yMin="([\d.]+)"\s+xMax="([\d.]+)"\s+yMax="([\d.]+)">(.*?)</word>',
                block,
                re.S,
            ):
                x0, y0, x1, y1 = (float(wm.group(k)) for k in range(1, 5))
                words.append(_norm_word(wm.group(5), x0, x1, y0, y1, 0.0, ""))
            pages.append(
                {
                    "number": i,
                    "width": width,
                    "height": height,
                    "words": words,
                    "has_text": bool(words),
                    "backend": "pdftotext -bbox-layout",
                }
            )
        return pages


BACKENDS = [
    ("pdfplumber", _backend_pdfplumber),
    ("pdfminer.six", _backend_pdfminer),
    ("pdftotext", _backend_poppler_bbox),
    ("pypdf", _backend_pypdf),
]


def extract(path, prefer=None, logger=None):
    """Try each backend in order; return (pages, backend_name, attempts).

    A backend counts as successful only if it produced at least one word somewhere.
    Partial success is still accepted: pages without a text layer stay has_text=False
    and are reported as `missing` by the caller rather than silently skipped.
    """
    attempts = []
    order = sorted(BACKENDS, key=lambda b: 0 if b[0] == prefer else 1) if prefer else BACKENDS
    for name, fn in order:
        try:
            pages = fn(path)
        except Exception as exc:  # noqa: BLE001 - a missing backend is expected
            attempts.append({"backend": name, "ok": False, "error": "%s: %s" % (type(exc).__name__, exc)})
            if logger:
                logger("backend %s unavailable: %s" % (name, exc))
            continue
        n_words = sum(len(p["words"]) for p in pages)
        ok = n_words > 0
        attempts.append({"backend": name, "ok": ok, "pages": len(pages), "words": n_words})
        if logger:
            logger("backend %s: pages=%d words=%d ok=%s" % (name, len(pages), n_words, ok))
        if ok:
            return pages, name, attempts
    return [], None, attempts
