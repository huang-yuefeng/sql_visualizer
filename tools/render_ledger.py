#!/usr/bin/env python3
"""Render the Source Ledger artifact HTML from /tmp/line_counts.json.

Hierarchy per request: Function (L1) → folder/file (L2) → count (L3).
Self-contained page (inline CSS only, both themes).
"""
import json
import html
import os

DATA = "/tmp/line_counts.json"
OUT = "/tmp/source_ledger.html"
VERSION = "v3.3.159"

d = json.load(open(DATA))

def file_lines(rel):
    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), rel), encoding="utf-8") as f:
        return sum(1 for _ in f)

# Precompute per-file totals (source) + sums
for section in ("backend", "frontend"):
    for rel in list(d[section].keys()):
        d[section][rel + "|total"] = file_lines(rel)
    # move totals out of the funcs dicts
    totals = {}
    for rel in list(d[section].keys()):
        if rel.endswith("|total"):
            totals[rel[:-6]] = d[section].pop(rel)
    d[section + "_totals"] = totals

def span(a, b):
    return b - a + 1

def esc(s):
    return html.escape(s)

# ── Aggregates ────────────────────────────────────────────────────────
back_files = sorted((k for k in d["backend"] if not k.endswith("|total")),
                    key=lambda r: (r.rsplit("/", 1)[0], r))
front_files = sorted((k for k in d["frontend"] if not k.endswith("|total")),
                     key=lambda r: (r.rsplit("/", 1)[0], r))
docs = sorted(d["docs"].items(), key=lambda kv: kv[1], reverse=True)

b_lines = sum(d["backend_totals"].get(r, file_lines(r)) for r in back_files)
f_lines = sum(d["frontend_totals"].get(r, file_lines(r)) for r in front_files)
dl_lines = sum(d["docs"].values())
b_funcs = sum(len(d["backend"][r]) for r in back_files)
f_funcs = sum(len(d["frontend"][r]) for r in front_files)

# Biggest functions (for a "weight" highlight)
big = []
for rel in back_files:
    for n, a, b in d["backend"][rel]:
        big.append((span(a, b), n, rel))
for rel in front_files:
    for n, a, b in d["frontend"][rel]:
        big.append((span(a, b), n, rel))
big.sort(reverse=True)
bigset = {(n, rel) for _, n, rel in big[:25]}

# ── CSS ───────────────────────────────────────────────────────────────
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
html { -webkit-text-size-adjust:100%; }
body {
  margin:0; background:var(--bg); color:var(--ink);
  font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  font-size:15px; line-height:1.5;
}
.mono, .fn, .fp, .cnt, .docname, .docpath, .filetotal, .tot-num {
  font-family:ui-monospace,"SF Mono","Cascadia Code","JetBrains Mono",Menlo,Consolas,monospace;
  font-variant-numeric:tabular-nums;
}
.wrap { max-width:1180px; margin:0 auto; padding:40px 28px 72px; }

/* header */
header { margin-bottom:28px; }
.eyebrow {
  font-size:11px; letter-spacing:.14em; text-transform:uppercase; color:var(--muted);
  display:flex; align-items:center; gap:10px; margin-bottom:10px;
}
.eyebrow::before { content:""; width:18px; height:2px; background:var(--accent); }
h1 {
  font-size:40px; line-height:1.05; margin:0 0 8px; letter-spacing:-.02em;
  text-wrap:balance;
}
.sub { color:var(--muted); margin:0 0 26px; max-width:60ch; }
.totals { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; }
.tcard {
  background:var(--surface); border:1px solid var(--border); border-radius:10px;
  padding:14px 16px; box-shadow:var(--shadow);
}
.tcard .lab { font-size:11px; letter-spacing:.08em; text-transform:uppercase; color:var(--muted); }
.tcard .val { font-size:24px; font-weight:650; margin-top:2px; }
.tcard .val small { font-size:13px; color:var(--faint); font-weight:400; }
.tcard .val .dot { color:var(--accent); }

/* jump index */
nav.index { margin:22px 0 8px; }
nav.index h2 { font-size:12px; letter-spacing:.12em; text-transform:uppercase; color:var(--muted); margin:0 0 10px; }
.chips { display:flex; flex-wrap:wrap; gap:6px; }
.chips a {
  font-family:ui-monospace,Menlo,Consolas,monospace; font-size:12px;
  color:var(--muted); text-decoration:none;
  border:1px solid var(--border); border-radius:999px; padding:3px 10px;
  background:var(--surface);
}
.chips a:hover { color:var(--accent); border-color:var(--accent); }

/* sections */
section { margin-top:34px; }
.sec-head { display:flex; align-items:baseline; gap:12px; border-bottom:1px solid var(--border); padding-bottom:10px; margin-bottom:6px; }
.sec-head h2 { margin:0; font-size:22px; letter-spacing:-.01em; }
.sec-head .meta { color:var(--faint); font-size:13px; }
.sec-mark { width:10px; height:10px; border-radius:3px; align-self:center; }
.sec-mark.bk { background:var(--accent); }
.sec-mark.fe { background:var(--blue); }
.sec-mark.dc { background:var(--orange); }

.folder {
  margin:22px 0 2px; font-size:13px; color:var(--muted);
  letter-spacing:.03em; display:flex; align-items:center; gap:8px;
}
.folder::before { content:"▸"; color:var(--faint); }
.folder code { color:var(--faint); font-family:ui-monospace,Menlo,monospace; }

/* file group */
.file {
  background:var(--surface); border:1px solid var(--border); border-radius:10px;
  box-shadow:var(--shadow); margin:10px 0;
}
.file-head {
  display:flex; align-items:baseline; gap:10px; flex-wrap:wrap;
  padding:10px 16px; border-bottom:1px solid var(--border); cursor:default;
}
.file-name { font-weight:650; font-family:ui-monospace,Menlo,Consolas,monospace; font-size:14.5px; }
.file-path { color:var(--faint); font-size:12px; font-family:ui-monospace,Menlo,monospace; }
.file-total { margin-left:auto; font-family:ui-monospace,Menlo,monospace; font-size:12.5px; color:var(--muted); }
.file-total b { color:var(--ink); font-weight:600; }
.funcs { margin:0; padding:6px 8px; list-style:none; }
.frow {
  display:grid; grid-template-columns:minmax(0,1fr) max-content max-content;
  gap:14px; align-items:baseline; padding:3px 8px; border-radius:6px;
}
.frow:hover { background:var(--surface2); }
.frow.weight .fn::after { content:""; display:inline-block; width:6px; height:6px; border-radius:50%; background:var(--gold); margin-left:8px; vertical-align:1px; }
.fn { font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace; font-size:13.5px; overflow-wrap:anywhere; }
.fn .cls { color:var(--faint); }
.fp { color:var(--faint); font-size:12px; white-space:nowrap; }
.cnt { color:var(--muted); font-size:12.5px; text-align:right; min-width:52px; }

/* documents */
.docs { display:grid; gap:0; }
.docrow {
  display:grid; grid-template-columns:minmax(0,1fr) max-content;
  gap:14px; padding:7px 4px; border-bottom:1px solid var(--border); align-items:baseline;
}
.docrow .docname { font-family:ui-monospace,Menlo,monospace; font-size:13.5px; overflow-wrap:anywhere; }
.docrow .docpath { color:var(--faint); font-size:12px; }
.docrow .dcnt { font-family:ui-monospace,Menlo,monospace; font-size:13px; color:var(--muted); text-align:right; }
.docrow .dcnt .bar { display:inline-block; height:9px; border-radius:3px; background:var(--accent); vertical-align:middle; margin-right:8px; }

footer { margin-top:44px; color:var(--faint); font-size:12.5px; border-top:1px solid var(--border); padding-top:14px; }
footer code { font-family:ui-monospace,Menlo,monospace; }
@media (max-width:640px) {
  .wrap { padding:24px 16px 56px; }
  h1 { font-size:30px; }
  .frow { grid-template-columns:minmax(0,1fr) max-content; }
  .fp { display:none; }
}
"""

# ── Build function rows ───────────────────────────────────────────────
def fn_rows(rel, funcs, total, section):
    rows = []
    for name, a, b in funcs:
        c = span(a, b)
        cls = "frow" + (" weight" if (name, rel) in bigset else "")
        # class-chain dot → faint
        disp = esc(name)
        if "." in name:
            clsname, meth = name.rsplit(".", 1)
            disp = f'<span class="cls">{esc(clsname)}.</span>{esc(meth)}'
        basename = rel.rsplit("/", 1)[1]
        rows.append(
            f'<li class="{cls}">'
            f'<span class="fn">{disp}</span>'
            f'<span class="fp">{esc(basename)}</span>'
            f'<span class="cnt">{c}</span>'
            f"</li>"
        )
    return "".join(rows)

def file_group(rel, funcs, total, fid):
    folder, fname = rel.rsplit("/", 1)
    return (
        f'<div class="file" id="{fid}">'
        f'<div class="file-head"><span class="file-name">{esc(fname)}</span>'
        f'<span class="file-path">{esc(folder)}/</span>'
        f'<span class="file-total"><b>{total}</b> lines</span></div>'
        f'<ul class="funcs">{fn_rows(rel, funcs, total, "")}</ul>'
        f"</div>"
    )

# ── Assemble ──────────────────────────────────────────────────────────
max_doc = max((c for _, c in docs), default=1)

parts = []
parts.append("<title>Source Ledger</title>")
parts.append("<style>" + CSS + "</style>")

parts.append('<div class="wrap">')
parts.append("<header>")
parts.append('<div class="eyebrow">SQL Data Flow Visualizer · ' + VERSION + "</div>")
parts.append("<h1>Source Ledger</h1>")
parts.append('<p class="sub">Function-level line counts for the codebase and its documents, '
             "at the release commit. Each entry is Function → file → lines; files are grouped by folder.</p>")
parts.append('<div class="totals">')
parts.append(f'<div class="tcard"><div class="lab">Backend · Python</div><div class="val">{b_lines:,}<small> lines · {b_funcs} functions · {len(back_files)} files</small></div></div>')
parts.append(f'<div class="tcard"><div class="lab">Frontend · React</div><div class="val">{f_lines:,}<small> lines · {f_funcs} functions · {len(front_files)} files</small></div></div>')
parts.append(f'<div class="tcard"><div class="lab">Documents</div><div class="val">{dl_lines:,}<small> lines · {len(docs)} files</small></div></div>')
parts.append(f'<div class="tcard"><div class="lab">Total</div><div class="val"><span class="dot">•</span>{b_lines + f_lines:,}<small> source lines</small></div></div>')
parts.append("</div>")
parts.append("</header>")

# jump index
parts.append('<nav class="index"><h2>Jump to file</h2><div class="chips">')
for rel in back_files:
    parts.append(f'<a href="#bk-{esc(rel)}">{esc(rel.rsplit("/",1)[1])}</a>')
for rel in front_files:
    parts.append(f'<a href="#fe-{esc(rel)}">{esc(rel.rsplit("/",1)[1])}</a>')
parts.append("</div></nav>")

# Backend
parts.append('<section id="backend">')
parts.append('<div class="sec-head"><span class="sec-mark bk"></span><h2>Backend</h2>'
             f'<span class="meta">backend/app · {b_lines:,} lines · {b_funcs} functions</span></div>')
cur = None
for rel in back_files:
    folder = rel.rsplit("/", 1)[0]
    if folder != cur:
        parts.append(f'<div class="folder">backend/app/<code>{esc(folder.removeprefix("backend/app/"))}</code></div>')
        cur = folder
    parts.append(file_group(rel, d["backend"][rel], d["backend_totals"][rel], "bk-" + rel))
parts.append("</section>")

# Frontend
parts.append('<section id="frontend">')
parts.append('<div class="sec-head"><span class="sec-mark fe"></span><h2>Frontend</h2>'
             f'<span class="meta">frontend/src · {f_lines:,} lines · {f_funcs} functions</span></div>')
cur = None
for rel in front_files:
    folder = rel.rsplit("/", 1)[0]
    if folder != cur:
        parts.append(f'<div class="folder">frontend/src/<code>{esc(folder.removeprefix("frontend/src/"))}</code></div>')
        cur = folder
    parts.append(file_group(rel, d["frontend"][rel], d["frontend_totals"][rel], "fe-" + rel))
parts.append("</section>")

# Documents
parts.append('<section id="docs">')
parts.append('<div class="sec-head"><span class="sec-mark dc"></span><h2>Documents</h2>'
             f'<span class="meta">{dl_lines:,} lines · {len(docs)} files</span></div>')
parts.append('<div class="docs">')
for rel, c in docs:
    width = max(2, round(100 * c / max_doc))
    parts.append(
        f'<div class="docrow"><span class="docname">{esc(rel)}</span>'
        f'<span class="dcnt"><span class="bar" style="width:{width}px"></span>{c}</span></div>'
    )
parts.append("</div></section>")

parts.append("<footer>Generated from the v3.3.159 working tree. "
             "Python functions measured via AST (module-level defs + class methods); "
             "JavaScript/JSX via a brace-aware scanner (components + top-level functions). "
             "Counts are line spans (start→end), matching <code>wc -l</code> file totals. "
             "Gold dot = among the 25 largest functions.</footer>")
parts.append("</div>")

open(OUT, "w", encoding="utf-8").write("".join(parts))
print("wrote", OUT, len("".join(parts)), "bytes")
