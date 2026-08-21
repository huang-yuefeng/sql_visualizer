#!/usr/bin/env python3
"""Render the comprehensive Source Ledger HTML from /tmp/line_counts_full.json.

Hierarchy: Area (section) → folder → file → lines; function rows for code
files. Self-contained, both themes, no external assets.
"""
import json
import html
import collections
import os

DATA = "/tmp/line_counts_full.json"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "source_ledger_full.html")

d = json.load(open(DATA))
files = d["files"]
areas = d["areas"]

AREA_LABEL = {
    "backend_app": "Backend · app",
    "backend_tests": "Backend · tests",
    "backend_root": "Backend · root",
    "frontend_src": "Frontend · src",
    "frontend_tests": "Frontend · tests",
    "frontend_root": "Frontend · root",
    "e2e_tests": "E2E tests",
    "samples": "Samples",
    "tools": "Tools",
    "wiki": "Wiki docs",
    "root": "Repo root",
}
AREA_ORDER = ["backend_app", "backend_tests", "backend_root", "frontend_src",
              "frontend_tests", "frontend_root", "e2e_tests", "samples",
              "tools", "wiki", "root"]
AREA_HUE = {
    "backend_app": "green", "backend_tests": "green",
    "backend_root": "green",
    "frontend_src": "blue", "frontend_tests": "blue", "frontend_root": "blue",
    "e2e_tests": "purple",
    "samples": "gold", "tools": "orange", "wiki": "orange", "root": "gray",
}


def esc(s):
    return html.escape(str(s))


def span(a, b):
    return b - a + 1


def fmt(n):
    return f"{n:,}"


# largest functions across all code
big = []
for area in AREA_ORDER:
    for rel, v in files.get(area, {}).items():
        for name, a, b in v["funcs"]:
            big.append((span(a, b), name, rel, area))
big.sort(reverse=True)
bigset = {(n, rel) for _, n, rel, _ in big[:30]}

CSS = """
:root {
  --bg:#F6F8F5; --surface:#FFFFFF; --surface2:#EFF2EE;
  --ink:#1B211D; --muted:#5F6B64; --faint:#8A948D;
  --border:#DCE3DC; --accent:#1FA855; --accent-soft:#E4F4EA;
  --blue:#1769C0; --orange:#B74B1B; --purple:#7D3C98; --red:#C0342F; --gold:#B8860B;
  --shadow:0 1px 2px rgba(20,40,28,.05);
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg:#0F1311; --surface:#161B17; --surface2:#1B211D;
    --ink:#E4EAE5; --muted:#9AA69D; --faint:#6E7971;
    --border:#26302A; --accent:#3ECF7C; --accent-soft:#16251C;
    --blue:#4D9BE6; --orange:#E08A55; --purple:#B87FD6; --red:#E96A64; --gold:#D3A32A;
    --shadow:0 1px 2px rgba(0,0,0,.4);
  }
}
:root[data-theme="dark"] {
  --bg:#0F1311; --surface:#161B17; --surface2:#1B211D;
  --ink:#E4EAE5; --muted:#9AA69D; --faint:#6E7971;
  --border:#26302A; --accent:#3ECF7C; --accent-soft:#16251C;
  --blue:#4D9BE6; --orange:#E08A55; --purple:#B87FD6; --red:#E96A64; --gold:#D3A32A;
  --shadow:0 1px 2px rgba(0,0,0,.4);
}
* { box-sizing:border-box; }
body {
  margin:0; background:var(--bg); color:var(--ink);
  font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  font-size:15px; line-height:1.5;
}
.wrap { max-width:1180px; margin:0 auto; padding:40px 28px 72px; }
.mono { font-family:ui-monospace,"SF Mono","Cascadia Code",Menlo,Consolas,monospace; font-variant-numeric:tabular-nums; }
header { margin-bottom:26px; }
.eyebrow { font-size:11px; letter-spacing:.14em; text-transform:uppercase; color:var(--muted); display:flex; align-items:center; gap:10px; margin-bottom:10px; }
.eyebrow::before { content:""; width:18px; height:2px; background:var(--accent); }
h1 { font-size:40px; line-height:1.05; margin:0 0 8px; letter-spacing:-.02em; text-wrap:balance; }
.sub { color:var(--muted); margin:0 0 24px; max-width:70ch; }
.totals { display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:12px; }
.tcard { background:var(--surface); border:1px solid var(--border); border-radius:10px; padding:14px 16px; box-shadow:var(--shadow); }
.tcard .lab { font-size:11px; letter-spacing:.08em; text-transform:uppercase; color:var(--muted); }
.tcard .val { font-size:23px; font-weight:650; margin-top:2px; }
.tcard .val small { font-size:12px; color:var(--faint); font-weight:400; }
nav.index { margin:20px 0 6px; }
nav.index h2 { font-size:12px; letter-spacing:.12em; text-transform:uppercase; color:var(--muted); margin:0 0 10px; }
.chips { display:flex; flex-wrap:wrap; gap:6px; }
.chips a { font-family:ui-monospace,Menlo,Consolas,monospace; font-size:12px; color:var(--muted); text-decoration:none; border:1px solid var(--border); border-radius:999px; padding:3px 10px; background:var(--surface); }
.chips a:hover { color:var(--accent); border-color:var(--accent); }
section { margin-top:30px; }
.sec-head { display:flex; align-items:baseline; gap:12px; border-bottom:1px solid var(--border); padding-bottom:10px; margin-bottom:4px; }
.sec-head h2 { margin:0; font-size:22px; letter-spacing:-.01em; }
.sec-head .meta { color:var(--faint); font-size:13px; }
.sec-mark { width:10px; height:10px; border-radius:3px; align-self:center; }
.sec-mark.green { background:var(--accent); } .sec-mark.blue { background:var(--blue); }
.sec-mark.purple { background:var(--purple); } .sec-mark.orange { background:var(--orange); }
.sec-mark.gold { background:var(--gold); } .sec-mark.gray { background:var(--faint); }
.folder { margin:18px 0 2px; font-size:13px; color:var(--muted); letter-spacing:.03em; display:flex; align-items:center; gap:8px; }
.folder::before { content:"▸"; color:var(--faint); }
.folder .fstat { margin-left:auto; color:var(--faint); font-size:12px; }
.file { background:var(--surface); border:1px solid var(--border); border-radius:10px; box-shadow:var(--shadow); margin:8px 0; }
.file-head { display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; padding:9px 16px; border-bottom:1px solid var(--border); }
.file-name { font-weight:650; font-family:ui-monospace,Menlo,Consolas,monospace; font-size:14px; }
.ftag { font-size:10.5px; letter-spacing:.06em; text-transform:uppercase; color:var(--faint); border:1px solid var(--border); border-radius:5px; padding:0 6px; }
.file-total { margin-left:auto; font-family:ui-monospace,Menlo,monospace; font-size:12.5px; color:var(--muted); }
.file-total b { color:var(--ink); font-weight:600; }
.funcs { margin:0; padding:6px 8px; list-style:none; }
.frow { display:grid; grid-template-columns:minmax(0,1fr) max-content max-content; gap:14px; align-items:baseline; padding:3px 8px; border-radius:6px; }
.frow:hover { background:var(--surface2); }
.frow.weight .fn::after { content:""; display:inline-block; width:6px; height:6px; border-radius:50%; background:var(--gold); margin-left:8px; vertical-align:1px; }
.fn { font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace; font-size:13px; overflow-wrap:anywhere; }
.fn .cls { color:var(--faint); }
.fp { color:var(--faint); font-size:12px; white-space:nowrap; }
.cnt { color:var(--muted); font-size:12.5px; text-align:right; min-width:52px; }
.datafile { display:grid; grid-template-columns:minmax(0,1fr) max-content; gap:14px; align-items:baseline; padding:3px 16px; }
.datafile .dn { font-family:ui-monospace,Menlo,monospace; font-size:12.5px; overflow-wrap:anywhere; }
.datafile .dc { font-family:ui-monospace,Menlo,monospace; font-size:12.5px; color:var(--muted); text-align:right; }
details { margin:6px 0; }
summary { cursor:pointer; padding:8px 14px; font-size:13px; color:var(--muted); background:var(--surface); border:1px solid var(--border); border-radius:8px; }
summary:hover { border-color:var(--accent); }
summary .s { color:var(--ink); font-family:ui-monospace,Menlo,monospace; font-weight:600; }
footer { margin-top:44px; color:var(--faint); font-size:12.5px; border-top:1px solid var(--border); padding-top:14px; }
footer code { font-family:ui-monospace,Menlo,monospace; }
@media (max-width:640px) { .wrap { padding:24px 16px 56px; } h1 { font-size:30px; } .fp { display:none; } .frow { grid-template-columns:minmax(0,1fr) max-content; } }
"""


def fn_rows(rel, funcs):
    rows = []
    for name, a, b in funcs:
        c = span(a, b)
        cls = "frow" + (" weight" if (name, rel) in bigset else "")
        disp = esc(name)
        if "." in name:
            clsname, meth = name.rsplit(".", 1)
            disp = f'<span class="cls">{esc(clsname)}.</span>{esc(meth)}'
        basename = rel.rsplit("/", 1)[-1]  # [-1] falls back to the whole path for root-level files
        rows.append(f'<li class="{cls}"><span class="fn">{disp}</span>'
                    f'<span class="fp">{esc(basename)}</span><span class="cnt">{c}</span></li>')
    return "".join(rows)


def file_group(rel, v):
    folder, fname = (rel.rsplit("/", 1) if "/" in rel else ("/", rel))
    fl = v["lines"]
    funcs = v["funcs"]
    tag = fname.rsplit(".", 1)[-1].upper() if "." in fname else ""
    body = ""
    if funcs:
        body = f'<ul class="funcs">{fn_rows(rel, funcs)}</ul>'
    else:
        body = (f'<div class="datafile"><span class="dn">{esc(rel)}</span>'
                f'<span class="dc">{fl}</span></div>')
    return (f'<div class="file"><div class="file-head">'
            f'<span class="file-name">{esc(fname)}</span>'
            f'<span class="ftag">{esc(tag)}</span>'
            f'<span class="file-total"><b>{fl}</b> lines'
            f'{f" · {len(funcs)} functions" if funcs else ""}</span></div>{body}</div>')


def folder_groups(area):
    by_folder = collections.OrderedDict()
    for rel, v in sorted(files.get(area, {}).items()):
        folder = rel.rsplit("/", 1)[0] if "/" in rel else "/"
        by_folder.setdefault(folder, []).append((rel, v))
    return by_folder


parts = []
parts.append("<title>Source Ledger</title>")
parts.append("<style>" + CSS + "</style>")
parts.append('<div class="wrap">')

tot_files = sum(a["files"] for a in areas.values())
tot_lines = sum(a["lines"] for a in areas.values())
src_areas = ["backend_app", "backend_tests", "frontend_src", "frontend_tests", "e2e_tests"]
src_lines = sum(areas[a]["lines"] for a in src_areas)
src_files = sum(areas[a]["files"] for a in src_areas)
src_funcs = sum(areas[a]["funcs"] for a in src_areas)
doc_areas = ["backend_root", "frontend_root", "tools", "wiki", "root"]

parts.append("<header>")
parts.append('<div class="eyebrow">SQL Data Flow Visualizer · full folder scan</div>')
parts.append("<h1>Source Ledger</h1>")
parts.append('<p class="sub">Whole-project line counts. Every text file in the folder is counted '
             'once; function rows are shown for code files. Build artifacts '
             '(frontend/dist, backend/app/static*, node_modules, wheels, images, archives, caches) are excluded.</p>')
parts.append('<div class="totals">')
parts.append(f'<div class="tcard"><div class="lab">All files</div><div class="val">{fmt(tot_lines)}<small> lines · {tot_files} files</small></div></div>')
parts.append(f'<div class="tcard"><div class="lab">Source code</div><div class="val">{fmt(src_lines)}<small> lines · {src_files} files · {src_funcs} functions</small></div></div>')
parts.append(f'<div class="tcard"><div class="lab">Test data</div><div class="val">{fmt(areas["samples"]["lines"])}<small> lines · {areas["samples"]["files"]} sql/csv</small></div></div>')
parts.append(f'<div class="tcard"><div class="lab">Tests + fixtures</div><div class="val">{fmt(areas["backend_tests"]["lines"])}<small> lines · {areas["backend_tests"]["files"]} files</small></div></div>')
parts.append("</div>")
parts.append("</header>")

parts.append('<nav class="index"><h2>Sections</h2><div class="chips">')
for a in AREA_ORDER:
    parts.append(f'<a href="#sec-{a}">{esc(AREA_LABEL[a])}</a>')
parts.append("</div></nav>")

for a in AREA_ORDER:
    gfiles = files.get(a, {})
    if not gfiles:
        continue
    ainfo = areas[a]
    parts.append(f'<section id="sec-{a}">')
    parts.append(f'<div class="sec-head"><span class="sec-mark {AREA_HUE[a]}"></span>'
                 f'<h2>{esc(AREA_LABEL[a])}</h2>'
                 f'<span class="meta">{fmt(ainfo["lines"])} lines · {ainfo["files"]} files'
                 f'{f" · {ainfo["funcs"]} functions" if ainfo["funcs"] else ""}</span></div>')
    for folder, rels in folder_groups(a).items():
        fsum = sum(v["lines"] for _, v in rels)
        parts.append(f'<div class="folder"><span>{esc(folder)}</span>'
                     f'<span class="fstat">{fmt(fsum)} lines · {len(rels)} files</span></div>')
        # samples: collapsible per subdir; others: file groups with functions
        if a == "samples":
            parts.append('<details open><summary><span class="s">' + esc(folder) +
                         f'</span> — {fmt(fsum)} lines, {len(rels)} files</summary>')
            for rel, v in rels:
                parts.append(f'<div class="datafile"><span class="dn">{esc(rel)}</span>'
                             f'<span class="dc">{v["lines"]}</span></div>')
            parts.append("</details>")
        else:
            for rel, v in rels:
                parts.append(file_group(rel, v))
    parts.append("</section>")

parts.append("<footer>Generated from the whole project folder via <code>tools/line_count_full.py</code> "
             "(exclusions: node_modules, .git, caches, frontend/dist, backend/app/static + static.bak.*, "
             "docker_image, test-results, binary files, archives). "
             "Python functions via AST; JS/JSX via brace-aware scan. File totals = logical line "
             "counts; function rows use 1-based start→end line spans. Gold dot = among the 30 largest functions.</footer>")
parts.append("</div>")

open(OUT, "w", encoding="utf-8").write("".join(parts))
print("wrote", OUT, len("".join(parts)), "bytes")
