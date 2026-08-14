#!/usr/bin/env python3
"""Comprehensive line count over the whole project folder.

Counts every text file (line = number of logical lines), excludes:
  - node_modules / .git / caches (__pycache__, .pytest_cache, analysis_cache)
  - build output (frontend/dist), docker_image release parts, test-results
  - binary files (images, archives, wheels, etc.)
Function-level detail (name, start, end) is extracted for .py / .js / .jsx /
.mjs / .cjs files via AST / brace-aware scan (reusing line_count_summary.py).

Writes JSON to /tmp/line_counts_full.json and a self-contained HTML ledger to
tools/source_ledger_full.html.

Usage: python3 tools/line_count_full.py
"""
import ast
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Exclusions ─────────────────────────────────────────────────────────
# Deploy/build artifacts that duplicate frontend/src (bundled ELK + built
# assets). backend/app/static + static.bak.* are the baked-in frontend.
EXCLUDED_DIRS = {
    "node_modules", ".git", "__pycache__", ".pytest_cache", "analysis_cache",
    ".venv", "dist", "static", "docker_image", "test-results", ".claude",
    ".idea", "reports",
}
# dirs inside excluded-dir names (any depth)
EXCLUDED_PART = ("node_modules", ".git", "__pycache__", ".pytest_cache",
                 "analysis_cache", "dist", "static", "docker_image",
                 "test-results", ".claude", "reports")
BINARY_EXT = {
    "png", "bmp", "gif", "jpg", "jpeg", "svg", "webp", "ico", "avif",
    "wasm", "ttf", "otf", "woff", "woff2", "eot",
    "whl", "pyc", "pyo", "zip", "gz", "tar", "tgz", "tbz2", "xz", "7z", "rar", "jar",
    "class", "so", "o", "a", "dll", "exe", "db", "sqlite", "traineddata",
    "map", "pdf",
}
ARCHIVE_NAME_END = (".zip", ".tar.gz", ".tgz", ".tar", ".gz", ".7z", ".rar")


def excluded(path):
    parts = path.split(os.sep)
    if any(p in EXCLUDED_PART or p.startswith("static.bak.") for p in parts):
        return True
    return False


def is_text(path):
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    if ext in BINARY_EXT:
        return False
    if path.endswith(ARCHIVE_NAME_END):
        return False
    try:
        with open(path, "rb") as fh:
            head = fh.read(8192)
        if b"\x00" in head:
            return False
        head.decode("utf-8")
        return True
    except (UnicodeDecodeError, OSError):
        return False


def n_lines(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return sum(1 for _ in fh)


# ── Function extraction (reused) ───────────────────────────────────────
def py_functions(path):
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    tree = ast.parse(src)
    out = []

    def walk(node, chain):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = ".".join(chain + [child.name])
                out.append((name, child.lineno, child.end_lineno))
                walk(child, chain + [child.name])
            elif isinstance(child, ast.ClassDef):
                walk(child, chain + [child.name])

    walk(tree, [])
    return out


def _strip_strings(line):
    out, i, n = [], 0, len(line)
    while i < n:
        c = line[i]
        if c in ("'", '"'):
            q, j = c, i + 1
            while j < n:
                if line[j] == "\\":
                    j += 2; continue
                if line[j] == q:
                    break
                j += 1
            i = j + 1; out.append("  ")
        elif c == "`":
            j = i + 1
            while j < n:
                if line[j] == "\\":
                    j += 2; continue
                if line[j] == "`":
                    break
                j += 1
            i = j + 1; out.append("  ")
        elif c == "/" and i + 1 < n and line[i + 1] == "/":
            break
        elif c == "/" and i + 1 < n and line[i + 1] == "*":
            j = line.find("*/", i + 2)
            i = (j + 2) if j != -1 else n
            out.append("  ")
        else:
            out.append(c); i += 1
    return "".join(out)


def js_functions(path):
    with open(path, encoding="utf-8") as fh:
        lines = fh.readlines()
    n = len(lines)
    func_re = re.compile(r"(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)")
    const_fn_re = re.compile(r"const\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?function\b")
    const_arrow_re = re.compile(r"const\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(?[^=;]*\)\s*=>")
    class_re = re.compile(r"(?:export\s+)?class\s+([A-Za-z_$][\w$]*)")
    method_re = re.compile(r"^\s{2,}(?:async\s+)?([A-Za-z_$][\w$]*)\s*\([^;]*\)\s*\{\s*$")
    out = []

    def find_end(start_idx, open_line):
        depth = 0
        i = open_line
        while i < n:
            masked = _strip_strings(lines[i])
            depth += masked.count("{") - masked.count("}")
            if depth <= 0 and i >= open_line:
                return i
            i += 1
        return open_line

    i = 0
    while i < n:
        stripped = lines[i].strip()
        m = func_re.search(stripped)
        if m and "function" in stripped and not stripped.startswith("//"):
            j = i
            while j < n and "{" not in _strip_strings(lines[j]):
                j += 1
            if j < n:
                end = find_end(i, j)
                out.append((m.group(1), i + 1, end + 1)); i = end + 1; continue
        m = const_fn_re.search(stripped)
        if m:
            j = i
            while j < n and "{" not in _strip_strings(lines[j]):
                j += 1
            if j < n:
                end = find_end(i, j)
                out.append((m.group(1), i + 1, end + 1)); i = end + 1; continue
        m = const_arrow_re.search(stripped)
        if m:
            j = i
            while j < n:
                if "{" in _strip_strings(lines[j]):
                    break
                j += 1
            if j < n:
                end = find_end(i, j)
                out.append((m.group(1), i + 1, end + 1)); i = end + 1; continue
        m = class_re.search(stripped)
        if m:
            cls, j, depth = m.group(1), i, 0
            while j < n:
                masked = _strip_strings(lines[j])
                depth += masked.count("{") - masked.count("}")
                mm = method_re.match(lines[j])
                if mm and depth >= 1:
                    k = j
                    while k < n and "{" not in _strip_strings(lines[k]):
                        k += 1
                    end = find_end(j, k)
                    out.append((f"{cls}.{mm.group(1)}", j + 1, end + 1))
                    j = end + 1
                    depth = 0
                    for z in range(i, j):
                        depth += _strip_strings(lines[z]).count("{") - _strip_strings(lines[z]).count("}")
                    continue
                if depth <= 0 and j > i:
                    break
                j += 1
            i = j
            continue
        i += 1
    return out


# ── Area classification ────────────────────────────────────────────────
AREA_ORDER = ["backend_app", "backend_tests", "backend_root", "frontend_src",
              "frontend_tests", "frontend_root", "e2e_tests", "samples",
              "tools", "wiki", "root"]
AREA_LABEL = {
    "backend_app": "Backend — app",
    "backend_tests": "Backend — tests",
    "backend_root": "Backend — root",
    "frontend_src": "Frontend — src",
    "frontend_tests": "Frontend — tests",
    "frontend_root": "Frontend — root",
    "e2e_tests": "E2E tests",
    "samples": "Samples (SQL/CSV data)",
    "tools": "Tools",
    "wiki": "Wiki docs",
    "root": "Repo root",
}


def classify(rel):
    p = rel.replace(os.sep, "/")
    if "/__tests__/" in p:
        return "frontend_tests"
    if p.startswith("backend/app/"):
        return "backend_app"
    if p.startswith("backend/tests/"):
        return "backend_tests"
    if p.startswith("backend/"):
        return "backend_root"
    if p.startswith("frontend/src/"):
        return "frontend_src"
    if p.startswith("frontend/"):
        return "frontend_root"
    if p.startswith("tests/"):
        return "e2e_tests"
    if p.startswith("samples/"):
        return "samples"
    if p.startswith("tools/"):
        return "tools"
    if p.startswith("wiki/"):
        return "wiki"
    return "root"


CODE_EXT = (".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx")


def main():
    report = {"files": {}, "areas": {}}
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
        for fn in sorted(filenames):
            path = os.path.join(dirpath, fn)
            if excluded(path) or not is_text(path):
                continue
            rel = os.path.relpath(path, ROOT)
            lines = n_lines(path)
            funcs = []
            if path.endswith(CODE_EXT):
                try:
                    funcs = py_functions(path) if path.endswith(".py") else js_functions(path)
                except (SyntaxError, UnicodeDecodeError):
                    funcs = []
            area = classify(rel)
            report["files"].setdefault(area, {})[rel] = {"lines": lines, "funcs": funcs}

    # totals
    for area in AREA_ORDER:
        files = report["files"].get(area, {})
        nf = len(files)
        nl = sum(v["lines"] for v in files.values())
        nfn = sum(len(v["funcs"]) for v in files.values())
        report["areas"][area] = {"files": nf, "lines": nl, "funcs": nfn}

    with open("/tmp/line_counts_full.json", "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)

    print(json.dumps(report["areas"], indent=1))
    print(f"TOTAL files: {sum(a['files'] for a in report['areas'].values())}")
    print(f"TOTAL lines: {sum(a['lines'] for a in report['areas'].values()):,}")


if __name__ == "__main__":
    main()
