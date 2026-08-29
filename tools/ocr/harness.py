#!/usr/bin/env python3
"""
OCR loop harness for SQL screenshot reconstruction.

The loop (as agreed with the user):
  1. OpenCV pixel pre-analysis -> a NEAR-GROUND-TRUTH count, independent of OCR:
       * line count   (a line boundary is a row with NO pixels)
       * word count   (within a line, a word boundary is a pixel-less x-gap)
       * char count   (within a word, one connected component ~= one character)
     This is a recursive divide-and-conquer: script -> lines -> words -> chars.
  2. OCR each line (gutter stripped, LANCZOS zoomed).
  3. Verify OCR against the pixel count at all three levels. If the OCR count is
     LESS than the pixel count, the OCR missed something -> enhance (deeper zoom)
     and re-read, looping until the result stops improving.
  4. Unresolvable residual gaps + sqlglot validation -> reported to the human.

Offline only: cv2, numpy, rapidocr_onnxruntime (PP-OCRv3 models bundled in the
wheel), sqlglot. Super-resolution (cv2.dnn_superres) is NOT available offline, so
the "enhance" step is multi-scale LANCZOS zoom (which the spec lists as the
alternative to super-resolution).
"""

import argparse
import json
import os
import re
import sys
import tempfile

import cv2
import numpy as np

try:
    from rapidocr_onnxruntime import RapidOCR
except Exception as _e:  # pragma: no cover - environment hint
    RapidOCR = None
    _RAPIDOCR_IMPORT_ERR = _e

try:
    import sqlglot
    from sqlglot import exp
except Exception as _e:  # pragma: no cover
    sqlglot = None
    _SQLGLOT_IMPORT_ERR = _e


# --------------------------------------------------------------------------
# 1. OpenCV pixel pre-analysis (the near-ground-truth count)
# --------------------------------------------------------------------------

def load_bgr(path):
    """Load an image as BGR ndarray; falls back to PIL for exotic PNG modes."""
    img = cv2.imread(path)
    if img is not None:
        return img
    # L-H1: cv2 failed (exotic PNG mode) — fall back to PIL, with a helpful
    # error if PIL is missing too, and without leaking the PIL file handle.
    try:
        from PIL import Image
    except ImportError as e:
        raise RuntimeError(
            f"cannot read {path!r}: cv2.imread returned None and PIL is "
            f"unavailable ({e}) — install Pillow or convert the PNG mode"
        ) from e
    with Image.open(path) as pil:
        rgb = pil.convert("RGB")
    return cv2.cvtColor(np.array(rgb), cv2.COLOR_RGB2BGR)


def binarize(img):
    """Binary mask with text = white. Polarity is auto-detected so it works for
    both light-on-dark editor screenshots and dark-on-light scans."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    median = float(np.median(gray))
    margin = int(0.12 * 255)  # 30 — L-H2: the old max(12, ...) floor was dead
    if median < 128:
        # Dark background, light text — anything notably brighter is content.
        return ((gray > median + margin) * 255).astype(np.uint8)
    # Light background, dark text.
    return ((gray < median - margin) * 255).astype(np.uint8)


def detect_line_bands(binv, min_h=6, gap=2, row_frac=0.01):
    """Return [(y0, y1), ...] text-row bands via horizontal projection.

    A line boundary is a row with ~zero text pixels, so counting the bands is
    a pixel-derived LINE COUNT."""
    h, w = binv.shape
    rowsum = (binv > 0).sum(axis=1)
    thresh = max(3, int(w * row_frac))
    mask = rowsum >= thresh

    raw = []
    y0 = None
    for y in range(h):
        if mask[y] and y0 is None:
            y0 = y
        elif not mask[y] and y0 is not None:
            if y - y0 >= min_h:
                raw.append((y0, y))
            y0 = None
    if y0 is not None and h - y0 >= min_h:
        raw.append((y0, h))

    merged = []
    for b in raw:
        if merged and b[0] - merged[-1][1] <= gap:
            merged[-1] = (merged[-1][0], b[1])
        else:
            merged.append(b)
    return merged


def line_pixel_counts(band_bin, min_area=4, min_h=1, word_gap=12):
    """Recursive divide-and-conquer count for one line strip.

    One connected component (glyph) ~= one character; glyphs cluster into words
    by pixel-less x-gaps. Returns a dict:
      {n_chars, n_words, per_word_chars, left, right}
    where per_word_chars is the character count of each word (word -> chars).

    M-H3: min_h=1 — periods/commas/underscores are 1-2px-tall components;
    dropping them undercounted n_chars and emitted spurious char-gap flags.
    min_area still filters pure speckle noise."""
    n, _, stats, _ = cv2.connectedComponentsWithStats(band_bin, connectivity=8)
    xs = []
    for i in range(1, n):
        x, y, w, hh, area = stats[i]
        if area >= min_area and hh >= min_h:
            xs.append(x + w / 2.0)  # glyph center x

    if not xs:
        return {"n_chars": 0, "n_words": 0, "per_word_chars": [],
                "left": 0, "right": 0}

    xs_sorted = sorted(xs)
    # divide the line into words: a word boundary is a gap > word_gap
    words = []
    cur = [xs_sorted[0]]
    for i in range(1, len(xs_sorted)):
        if xs_sorted[i] - xs_sorted[i - 1] > word_gap:
            words.append(cur)
            cur = [xs_sorted[i]]
        else:
            cur.append(xs_sorted[i])
    words.append(cur)

    per_word_chars = [len(w) for w in words]
    return {
        "n_chars": len(xs_sorted),
        "n_words": len(words),
        "per_word_chars": per_word_chars,
        "left": int(xs_sorted[0] - word_gap),
        "right": int(xs_sorted[-1] + word_gap),
    }


def super_resolve(img, scale, iterations=6, lam=0.6):
    """Learning-free iterative back-projection super-resolution (Irani & Peleg,
    1991). Reconstructs the high-frequency detail that pure interpolation blurs
    away by enforcing consistency with the observed low-res image — no model
    weights, so it runs fully offline."""
    h, w = img.shape[:2]
    f = img.astype(np.float32)
    H = cv2.resize(f, (w * scale, h * scale), interpolation=cv2.INTER_CUBIC)

    def degrade(x):
        # simulate the capture pipeline: anti-alias blur + downsample
        blur = cv2.GaussianBlur(x, (0, 0), sigmaX=1.0)
        return cv2.resize(blur, (w, h), interpolation=cv2.INTER_AREA)

    for _ in range(iterations):
        E = f - degrade(H)          # low-res error (what the estimate is missing)
        E_up = cv2.resize(E, (w * scale, h * scale), interpolation=cv2.INTER_CUBIC)
        H = H + lam * E_up          # back-project the error
    return np.clip(H, 0, 255).astype(np.uint8)


def detect_gutter_left(binv, max_x=150, min_gap=12):
    """Return the x column where code starts (after the line-number gutter).
    0 means 'no gutter detected' (crop nothing). The gutter is a left block of
    short content followed by a clean vertical whitespace gap.

    M-H4: min_gap is WIDE (12 cols) — a 3-column gap after an indented token
    is ordinary code spacing, not a gutter; and the returned x is clamped to
    w-1 so `binv[y0:y1, x0:]` can never become an empty crop."""
    colsum = (binv > 0).sum(axis=0)
    nonzero = colsum > 0
    w = len(colsum)
    first = 0
    while first < w and not nonzero[first]:
        first += 1
    if first >= w:
        return 0
    run = 0
    for c in range(first, min(w, first + max_x)):
        if not nonzero[c]:
            run += 1
            if run >= min_gap:
                return min(c + 1, w - 1)  # clamp: keep >=1 content column
        else:
            run = 0
    return 0


# --------------------------------------------------------------------------
# 2-3. Multi-scale RapidOCR + merge, escalating until no improvement
# --------------------------------------------------------------------------

class OcrEngine:
    def __init__(self):
        if RapidOCR is None:
            raise RuntimeError(f"rapidocr_onnxruntime unavailable: {_RAPIDOCR_IMPORT_ERR}")
        self._engine = RapidOCR()

    def _recognize(self, crop_path):
        res, _ = self._engine(str(crop_path))
        if not res:
            return "", 0.0, None, None
        texts, scores = [], []
        left = right = None
        for item in res:
            box, text, score = item
            text = (text or "").strip()
            if not text:
                continue
            texts.append(text)
            scores.append(float(score))
            pts = np.asarray(box, dtype=float).reshape(-1, 2)
            lx, rx = pts[:, 0].min(), pts[:, 0].max()
            left = lx if left is None else min(left, lx)
            right = rx if right is None else max(right, rx)
        if not texts:
            return "", 0.0, None, None
        return " ".join(texts), sum(scores) / len(scores), left, right

    @staticmethod
    def _upscale(crop, method, scale):
        if method == "sr":
            return super_resolve(crop, scale)
        return cv2.resize(crop, None, fx=scale, fy=scale,
                          interpolation=cv2.INTER_LANCZOS4)

    def ocr_band(self, img, y0, y1, x0=0, enhancers=None, tmpdir=None,
                 meta=None):
        """OCR one band (gutter cropped), escalating through a list of
        (method, scale) enhancers — LANCZOS zoom first, then super-resolution.
        Escalates while the read under-explains the pixel char count AND still
        improving; stops on no-improvement or the last enhancer."""
        enhancers = enhancers or [("lanczos", 6), ("lanczos", 8)]
        h, w = img.shape[:2]
        y0 = max(0, y0 - 2)
        y1 = min(h, y1 + 2)
        crop = img[y0:y1, x0:]
        target = meta["n_chars"] if meta else None

        attempts = []
        best_chars = -1
        for method, s in enhancers:
            big = self._upscale(crop, method, s)
            fd, path = tempfile.mkstemp(suffix=".png", dir=tmpdir)
            os.close(fd)
            cv2.imwrite(path, big)
            try:
                text, conf, left, right = self._recognize(path)
                if left is not None:
                    left /= s
                if right is not None:
                    right /= s
                attempts.append({"method": method, "scale": s, "text": text,
                                 "conf": conf, "left": left, "right": right})
            finally:
                os.unlink(path)

            n_chars = len(re.sub(r"\s+", "", attempts[-1]["text"]))
            if self._explains(attempts[-1], target):
                break
            # stop escalating if this enhancer read no more content than best
            if n_chars <= best_chars:
                break
            best_chars = max(best_chars, n_chars)

        if not attempts:
            return {"text": "", "conf": 0.0, "scale": None,
                    "method": None, "left": None, "right": None}

        # Best = most content read (longest), tie-break confidence.
        best = max(attempts, key=lambda a: (
            len(re.sub(r"\s+", "", a["text"])), a["conf"]))
        best["attempts"] = attempts
        return best

    @staticmethod
    def _explains(attempt, target):
        if not attempt["text"]:
            return False
        if target is None:
            return attempt["conf"] >= 0.90
        n_chars = len(re.sub(r"\s+", "", attempt["text"]))
        return n_chars >= target - 6


# --------------------------------------------------------------------------
# 4. Three-level verification: line / word / char
# --------------------------------------------------------------------------

def flag_band(meta, ocr, conf_lo=0.88, char_gap=8, word_gap=3, cover_gap=8):
    """Verify one OCR read against the pixel counts. Flags (ordered by severity):
      empty-ocr   — line has pixels but OCR read nothing  (LINE level)
      char-gap    — pixel char count >> OCR char count    (CHAR level)
      word-gap    — pixel word count >> OCR word count    (WORD level)
      left/right-uncovered — pixels beyond OCR coverage   (COVERAGE)
      low-conf    — RapidOCR confidence below threshold."""
    flags = []
    text = ocr["text"]

    if meta["n_chars"] == 0:
        if text:
            flags.append("ocr-extra")  # read text where no glyphs detected
        return flags

    # LINE level: content exists but nothing read back.
    if not text:
        flags.append(f"empty-ocr-{meta['n_chars']}-chars")
        return flags

    # CHAR level: OCR read fewer characters than the pixels contain.
    n_chars = len(re.sub(r"\s+", "", text))
    if meta["n_chars"] - n_chars > char_gap:
        flags.append(f"char-gap-{meta['n_chars']}-vs-{n_chars}")

    # WORD level: OCR read fewer words than the pixels contain. (RapidOCR can
    # collapse spaces, so this is a weaker signal than the char gap.)
    n_words = len(text.split())
    if meta["n_words"] - n_words > word_gap:
        flags.append(f"word-gap-{meta['n_words']}-vs-{n_words}")

    # COVERAGE: unread pixels at the left/right of the OCR bounding box.
    if ocr["left"] is not None and meta["left"] is not None \
            and ocr["left"] - meta["left"] > cover_gap:
        flags.append("left-uncovered")
    if ocr["right"] is not None and meta["right"] is not None \
            and meta["right"] - ocr["right"] > cover_gap:
        flags.append("right-uncovered")

    if ocr["conf"] < conf_lo:
        flags.append(f"low-conf-{ocr['conf']:.2f}")

    return flags


# --------------------------------------------------------------------------
# 5. sqlglot validation
# --------------------------------------------------------------------------

_SYSTEM_QUALIFIERS = {
    # L-H3: keywords ('values', 'lateral', 'mysql') removed — they masked
    # real errors; only actual system schemas/the DUAL table remain.
    "information_schema", "sys", "performance_schema", "dual",
}


def _sql_keywords():
    """SQL keywords/reserved words that would crowd out the identifier-vote.

    L13: derive the set from sqlglot's tokenizer so it tracks dialect keyword
    additions (MERGE/USING/ALTER/DROP/COLUMN/…) instead of drifting. The pinned
    tail covers the context-sensitive reserved words sqlglot does not emit as
    bare keywords (GROUP/ORDER/BY, CAST, window-frame CURRENT/PRECEDING/
    FOLLOWING, DDL PRIMARY/FOREIGN/KEY), plus the DDL words the denylist was
    previously missing, and doubles as the complete fallback when sqlglot is
    unavailable.
    """
    pinned = {
        "select", "from", "where", "group", "order", "by", "having", "join",
        "left", "right", "inner", "outer", "full", "cross", "on", "as", "and",
        "or", "not", "in", "is", "null", "like", "between", "exists", "case",
        "when", "then", "else", "end", "with", "union", "all", "distinct",
        "insert", "into", "values", "update", "set", "delete", "create",
        "table", "view", "partition", "over", "rows", "range", "preceding",
        "following", "current", "row", "limit", "offset", "asc", "desc",
        "cast", "interval",
        "date", "timestamp", "varchar", "decimal", "bigint", "string",
        "double",
        # L13: DDL/reserved words previously missing from the denylist.
        "merge", "using", "alter", "drop", "column", "key", "primary",
        "foreign", "default",
    }
    try:
        from sqlglot.tokens import Tokenizer
        pinned |= {k.lower() for k in Tokenizer.KEYWORDS}
    except Exception:  # pragma: no cover - sqlglot unavailable
        pass
    return frozenset(pinned)


# L-H4: SQL keywords always "win" the frequency vote and crowd out the
# identifier-spelling signal the vote exists for — exclude them (see
# _sql_keywords for the L13 tokenizer-derived build).
_SQL_KEYWORDS = _sql_keywords()

_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _split_on_semicolons(sql_text, dialect):
    """Split a script on real ';' tokens, keeping ';' inside string literals and
    comments intact (the tokenizer skips both). Falls back to a naive split only
    when tokenization itself fails."""
    try:
        tokens = sqlglot.tokens.Tokenizer(dialect=dialect).tokenize(sql_text)
    except Exception:  # pragma: no cover - tokenizer failure on exotic input
        return sql_text.split(";")
    parts = []
    start = 0
    for tok in tokens:
        if tok.token_type == sqlglot.tokens.TokenType.SEMICOLON:
            parts.append(sql_text[start : tok.start])
            start = tok.end + 1
    parts.append(sql_text[start:])
    return parts


def _parse_statements(sql_text, dialect, out):
    """Statement-split via sqlglot (M-H1: survives ';' inside string literals
    and comments). Falls back to a ';'-safe tokenizer split (L12) — reporting
    the per-statement parse error — when the whole-script parse raises."""
    try:
        stmts = sqlglot.parse(sql_text, read=dialect)
    except Exception as e:
        out["parse_errors"].append(_clip(str(e)))
        stmts = []
        for stmt in _split_on_semicolons(sql_text, dialect):
            stmt = stmt.strip()
            if not stmt:
                continue
            try:
                tree = sqlglot.parse_one(stmt, read=dialect)
            except Exception as e2:
                out["parse_errors"].append(_clip(str(e2)))
                continue
            if tree is not None:
                stmts.append(tree)
    return [s for s in stmts if s is not None]


def validate_sql(sql_text, dialect="hive"):
    """Parse the whole script and report parse errors + undeclared aliases."""
    if sqlglot is None:
        return {"error": f"sqlglot unavailable: {_SQLGLOT_IMPORT_ERR}"}

    out = {"parse_errors": [], "undeclared_qualifiers": [], "dialect": dialect}

    all_declared = set()
    undeclared = set()

    for tree in _parse_statements(sql_text, dialect, out):
        # M-H1: declared names are PER-STATEMENT scope — an alias declared in
        # one statement does not cover a qualifier in another (each statement
        # must carry its own FROM/CTE/alias declarations).
        declared = set()
        for t in tree.find_all(exp.Table):
            # M-H2: only the effective reference (alias if present, else the
            # table's own name) — adding t.name unconditionally let a physical
            # table name silence undeclared qualifiers elsewhere.
            p = (t.alias_or_name or "").strip()
            if p:
                declared.add(p.lower())
        for s in tree.find_all(exp.Subquery):
            a = (s.alias or "").strip()
            if a:
                declared.add(a.lower())
        for c in tree.find_all(exp.CTE):
            a = (c.alias or "").strip()
            if a:
                declared.add(a.lower())
        for col in tree.find_all(exp.Column):
            q = (col.table or "").strip().lower()
            if q and q not in declared and q not in _SYSTEM_QUALIFIERS:
                undeclared.add(q)
        all_declared |= declared

    out["undeclared_qualifiers"] = sorted(undeclared)
    out["declared_aliases"] = sorted(all_declared)
    return out


def identifier_votes(sql_text):
    """Frequency vote over identifiers -> spot inconsistent spellings."""
    votes = {}
    for m in _IDENT_RE.findall(sql_text):
        m = m.lower()
        if m in _SQL_KEYWORDS:
            continue
        votes[m] = votes.get(m, 0) + 1
    long = {k: v for k, v in votes.items() if len(k) >= 4 and v >= 2}
    return long


def _clip(s, n=200):
    return s if len(s) <= n else s[: n - 3] + "..."


# --------------------------------------------------------------------------
# 6. Driver
# --------------------------------------------------------------------------

def process_image(path, engine=None, scales=(6, 8), sr_scales=(8, 12),
                  dialect="hive"):
    engine = engine or OcrEngine()
    img = load_bgr(path)
    binv = binarize(img)
    x0 = detect_gutter_left(binv)
    bands = detect_line_bands(binv)

    # escalation ladder: LANCZOS zoom first, then super-resolution.
    enhancers = ([("lanczos", s) for s in scales]
                 + [("sr", s) for s in sr_scales])

    lines = []
    with tempfile.TemporaryDirectory(prefix="ocr_") as tmpdir:
        # H-D2: the tempdir is removed when the block exits — mkdtemp leaked
        # one directory per image on every run.
        for y0, y1 in bands:
            band_bin = binv[y0:y1, x0:]
            meta = line_pixel_counts(band_bin)
            ocr = engine.ocr_band(img, y0, y1, x0=x0, enhancers=enhancers,
                                  tmpdir=tmpdir, meta=meta)
            flags = flag_band(meta, ocr)
            lines.append({
                "y0": y0, "y1": y1,
                "n_chars": meta["n_chars"], "n_words": meta["n_words"],
                "per_word_chars": meta["per_word_chars"],
                "text": ocr["text"], "conf": round(ocr["conf"], 3),
                "scale": f"{ocr.get('method') or ''}{ocr.get('scale') or ''}",
                "flags": flags,
            })

    stitched = "\n".join(l["text"] for l in lines if l["text"])
    val = validate_sql(stitched, dialect=dialect)
    votes = identifier_votes(stitched)

    return {
        "image": os.path.basename(path),
        "n_bands": len(bands),
        "n_flagged": sum(1 for l in lines if l["flags"]),
        "lines": lines,
        "validation": val,
        "identifier_votes": votes,
        "stitched": stitched,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="OCR harness for SQL screenshots")
    ap.add_argument("images", nargs="+")
    ap.add_argument("--dialect", default="hive")
    ap.add_argument("--scales", default="6,8,10,12")
    ap.add_argument("--out", default=None, help="write JSON report to this file")
    args = ap.parse_args(argv)

    scales = tuple(int(s) for s in args.scales.split(","))
    engine = OcrEngine()

    # M-H5: per-image isolation — one unreadable image must not abort the
    # whole batch; it contributes an error record instead.
    reports = []
    for p in args.images:
        try:
            reports.append(process_image(p, engine=engine, scales=scales,
                                         dialect=args.dialect))
        except Exception as e:  # noqa: BLE001 — report and continue
            reports.append({"image": os.path.basename(p),
                            "error": _clip(f"{type(e).__name__}: {e}")})

    payload = json.dumps(reports, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(payload)
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print(payload)


if __name__ == "__main__":
    main()
