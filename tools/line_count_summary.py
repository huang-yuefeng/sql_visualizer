#!/usr/bin/env python3
"""Line-count summary: function -> file -> line count, for backend .py and
frontend .js/.jsx source, plus document line counts.

Usage: python3 tools/line_count_summary.py [--json]
Outputs a nested markdown tree by default; --json dumps raw data.
"""
import ast
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── Python (AST) ──────────────────────────────────────────────────────
def py_functions(path):
    """Return list of (qualified_name, class_chain, lineno, end_lineno)."""
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    tree = ast.parse(src)
    out = []

    def walk(node, chain):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = ".".join(chain + [child.name])
                out.append((name, child.lineno, child.end_lineno))
                # recurse for nested defs (rare)
                walk(child, chain + [child.name])
            elif isinstance(child, ast.ClassDef):
                walk(child, chain + [child.name])

    walk(tree, [])
    return out


# ── JavaScript / JSX (brace-aware heuristic) ─────────────────────────
def _strip_strings(line):
    """Mask string contents so braces inside strings don't count."""
    out = []
    i = 0
    n = len(line)
    while i < n:
        c = line[i]
        if c == "'" or c == '"':
            q = c
            j = i + 1
            while j < n:
                if line[j] == "\\":
                    j += 2
                    continue
                if line[j] == q:
                    break
                j += 1
            i = j + 1
            out.append("  ")  # mask the whole string as two spaces
        elif c == "`":
            j = i + 1
            while j < n:
                if line[j] == "\\":
                    j += 2
                    continue
                if line[j] == "`":
                    break
                j += 1
            i = j + 1
            out.append("  ")
        elif c == "/" and i + 1 < n and line[i + 1] == "/":
            break  # line comment — rest is comment
        elif c == "/" and i + 1 < n and line[i + 1] == "*":
            # block comment start — mask to end of block (approx: to end of line)
            j = line.find("*/", i + 2)
            i = (j + 2) if j != -1 else n
            out.append("  ")
        else:
            out.append(c)
            i += 1
    return "".join(out)


def js_functions(path):
    """Return list of (name, lineno, end_lineno) for function-like defs."""
    with open(path, encoding="utf-8") as fh:
        lines = fh.readlines()
    n = len(lines)
    func_re = re.compile(
        r"(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)")
    const_fn_re = re.compile(r"const\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?function\b")
    const_arrow_re = re.compile(r"const\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(?[^=;]*\)\s*=>")
    export_arrow_re = re.compile(r"export\s+default\s+\(?[^=;]*\)\s*=>")
    class_re = re.compile(r"(?:export\s+)?class\s+([A-Za-z_$][\w$]*)")
    method_re = re.compile(r"^\s{2,}(?:async\s+)?([A-Za-z_$][\w$]*)\s*\([^;]*\)\s*\{\s*$")
    out = []

    def find_end(start_idx, open_line):
        """Given the 0-based index of the line containing '{', return the
        0-based index of the line closing the top-level brace."""
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
        line = lines[i]
        stripped = line.strip()
        m = func_re.search(stripped)
        if m and "function" in stripped and not stripped.startswith("//"):
            name = m.group(1)
            open_idx = i
            # find the '{' that opens the body (could be on same line)
            j = i
            while j < n and "{" not in _strip_strings(lines[j]):
                j += 1
            if j < n:
                end = find_end(i, j)
                out.append((name, i + 1, end + 1))
                i = end + 1
                continue
        m = const_fn_re.search(stripped)
        if m:
            name = m.group(1)
            j = i
            while j < n and "{" not in _strip_strings(lines[j]):
                j += 1
            if j < n:
                end = find_end(i, j)
                out.append((name, i + 1, end + 1))
                i = end + 1
                continue
        m = const_arrow_re.search(stripped)
        if m:
            name = m.group(1)
            # arrow body: look for the first line where a block '{' appears
            j = i
            while j < n:
                masked = _strip_strings(lines[j])
                if "{" in masked:
                    break
                # object-literal body on one line? e.g. const x = () => ({...})
                j += 1
            if j < n:
                end = find_end(i, j)
                out.append((name, i + 1, end + 1))
                i = end + 1
                continue
        m = class_re.search(stripped)
        if m:
            cls = m.group(1)
            # collect methods until closing brace of class
            j = i
            depth = 0
            while j < n:
                masked = _strip_strings(lines[j])
                depth += masked.count("{") - masked.count("}")
                mm = method_re.match(lines[j])
                if mm and depth >= 1:
                    # method: find its body close
                    k = j
                    while k < n and "{" not in _strip_strings(lines[k]):
                        k += 1
                    end = find_end(j, k)
                    out.append((f"{cls}.{mm.group(1)}", j + 1, end + 1))
                    j = end + 1
                    # recompute depth from current j
                    depth = 0
                    for z in range(i, j):
                        maskz = _strip_strings(lines[z])
                        depth += maskz.count("{") - maskz.count("}")
                    continue
                if depth <= 0 and j > i:
                    break
                j += 1
            i = j
            continue
        i += 1
    return out


# ── Documents ─────────────────────────────────────────────────────────
def doc_lines(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return sum(1 for _ in fh)


def main():
    as_json = "--json" in sys.argv
    report = {"backend": {}, "frontend": {}, "docs": {}}

    # Backend
    for dirpath, _dirs, files in os.walk(os.path.join(ROOT, "backend", "app")):
        for fn in sorted(files):
            if fn.endswith(".py"):
                path = os.path.join(dirpath, fn)
                rel = os.path.relpath(path, ROOT)
                funcs = py_functions(path)
                report["backend"][rel] = funcs

    # Frontend (skip __tests__)
    for dirpath, _dirs, files in os.walk(os.path.join(ROOT, "frontend", "src")):
        if "__tests__" in dirpath:
            continue
        for fn in sorted(files):
            if fn.endswith((".js", ".jsx")):
                path = os.path.join(dirpath, fn)
                rel = os.path.relpath(path, ROOT)
                funcs = js_functions(path)
                report["frontend"][rel] = funcs

    # Docs: markdown + shell scripts at root / tools / wiki
    doc_dirs = [ROOT,
                os.path.join(ROOT, "tools"),
                os.path.join(ROOT, "wiki")]
    for dd in doc_dirs:
        for fn in sorted(os.listdir(dd)):
            if fn.endswith(".md"):
                p = os.path.join(dd, fn)
                report["docs"][os.path.relpath(p, ROOT)] = doc_lines(p)
    for fn in ["release.sh", "target_deploy.sh", "deploy.sh", "build.sh", "check.sh", "fast_deploy.sh", "test-layout.sh"]:
        p = os.path.join(ROOT, fn)
        if os.path.exists(p):
            report["docs"][fn] = doc_lines(p)

    if as_json:
        print(json.dumps(report, indent=2))
        return

    # ── Markdown tree ──────────────────────────────────────────────
    def fmt_lines(a, b):
        return b - a + 1

    for section, data in (("Backend", report["backend"]),
                          ("Frontend", report["frontend"])):
        print(f"\n## {section}\n")
        for rel, funcs in data.items():
            folder, fname = os.path.split(rel)
            total = sum(fmt_lines(a, b) for _, a, b in funcs)
            file_lines = sum(1 for _ in open(os.path.join(ROOT, rel), encoding="utf-8"))
            print(f"### `{fname}`  —  `{folder}/`  (file {file_lines} lines)")
            for name, a, b in funcs:
                print(f"- **{name}**")
                print(f"  - `{rel}`")
                print(f"  - {fmt_lines(a, b)} lines")
            print()

    print("\n## Documents\n")
    for rel, cnt in report["docs"].items():
        print(f"- **{os.path.basename(rel)}**")
        print(f"  - `{rel}`")
        print(f"  - {cnt} lines")
        print()


if __name__ == "__main__":
    main()
