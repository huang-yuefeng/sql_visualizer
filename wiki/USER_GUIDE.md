# Data Flow Debugger — First-Tour User Guide

A practical walkthrough of the core workflow: **upload a folder of SQL scripts → (optionally) upload filter files → search a field → read the L1 and L2 views → walk the Field Story → compare with string matching**.

Everything here is based on the deployed UI (v3.3.194 or later). No SQL or internals knowledge required.

---

## 0. Before you start

- **An account.** Accounts are provisioned by your deployment's allowlist. Log in at the service URL with your email + password (minimum 6 characters). If your login fails, the account was likely not provisioned — ask your deployer.
- **A folder of SQL scripts** — the `.sql` files whose data flow you want to trace — zipped as a single `.zip`.

---

## 1. Upload a workspace (select folder)

1. Log in. The left panel is your workspace area.
2. Click **Upload .zip** and pick the zip of your script folder. (If you only have loose files, the panel can zip them for you via the secondary upload control.)
3. The service scans and indexes every script: this builds the table/field index that powers search and autocomplete. Watch the log panel for progress; the workspace header shows **"Indexed N scripts"** when done.
4. Your workspace stays on the server — next time you log in, open it from **My workspaces** or via its **`?ws=<id>`** link.

> **Tip** — after you re-upload or change scripts, the workspace's index can be refreshed by re-opening it; the header's "Indexed … ago" line tells you how fresh it is.

---

## 2. (Optional) Upload filter files

If the workspace is large, you can narrow the search scope with filter files.

1. Open the **Filter** section of the left panel and click **Upload filter**, supplying your filter files (CSV).
2. The debugger intersects the filters' scopes (A ∩ B): after this, **every search runs only inside that intersection**.
3. Rows that cannot be parsed or matched are **dropped and counted** — the panel reports them (ignored rows / ignored tables) rather than failing silently.
4. **Clear filter** removes the scope and returns you to the whole workspace.

> Filters are optional. Without them, search covers the entire workspace.

---

## 3. Search for a field

1. In the **Search** area, type the **table** name, then the **field** name. Both inputs offer autocomplete from the index (typo-tolerant, case-insensitive — `P_DT` and `p_dt` are the same field).
2. Press **Search**.
3. The result is a **view** (a tab appears in the view bar at the top):
   - **L1** — the cross-script pipeline: which scripts read/write the field's table, and how scripts connect.
   - **L2** — the per-script detail: the field's actual value flow inside one script, line by line.
4. If the field name matches on several tables, the resolved table is shown; if nothing matches, you get an explicit "not found" message — never a silent empty result.

> **Tip** — searches are per-user history and can be **pinned** (★) for quick re-run. The "Indexed … ago" line tells you how current the index is.

---

## 4. Read the L1 view (cross-script pipeline)

The L1 canvas shows **how scripts and tables connect across the whole workspace**:

- Each **script** is a node; **tables** are colored boxes (one color per table).
- **Edges** show read/write relationships between them.
- Clicking an **edge or node** highlights the corresponding SQL line in the script panel below.
- Double-click a **script node** to drill into that script's **L2 detail**.

Use L1 to answer: *which scripts touch this table, and in what order does data move between them?*

---

## 5. Open the L2 view (the field's actual value flow)

The L2 canvas shows the searched field's flow **inside one script**:

- Boxes are **tables/CTEs/aliases**; small chips are the **fields** on them.
- By default you see the **flow-only** view: only the edges the searched field's value actually travels.
- Toggle to the **full view** (the view bar) to see everything in the script as context — then toggle back.
- The **SQL panel** below always highlights the line behind whatever you click. The **Field Story bar** under it retells the same flow as ordered steps (next section).

Use L2 to answer: *where does this field's value come from, and where does it go inside this script?*

---

## 6. Walk the Field Story

Under the SQL panel is the **Field Story bar**: the field's flow retold as numbered steps.

- **Click a step chip (1, 2, 3, …)** — the corresponding SQL line is highlighted and **auto-scrolled to the middle of the panel**.
- **◀ / ▶** move back and forward through the steps; **▶/⏸** autoplay walks them (3 seconds per step).
- The stages, in order: **Birth** (where the field's value is first produced) → **Written** → **Read** → **Reappears** (the field named again at another line — a group key, join leg, predicate, or window partition) → **Joined/Transformed** → **Filtered** → **Consumed** (its final write).
- Steps that sit on the same SQL line are told as one step; clicking it again re-centers the line.

Use the Field Story to answer: *in order, what happens to this field — in plain SQL lines I can read?*

---

## 7. Compare with string matching (the diff layer)

The **string-match diff layer** overlays a naive, case-insensitive text search on top of the flow — so you can check the flow against raw string matches:

1. In the Field Story bar, click the small **circle toggle** ("Show the string-match bands"). Every line in the script that merely **contains the field's name** (case-insensitive) gets a band:
   - **Green band** — the string-match line **is** covered by the field's flow.
   - **Amber/red band** — the string-match line is **not** in the flow (a difference worth investigating: a comment, an unrelated same-name column, or a real gap).
   - The readout shows **"N string matches · M in flow · K not in flow"** — the difference at a glance.
2. Activating the layer automatically scrolls to the **first match**; **◀ / ▶** browse all matches (each lands centered in the panel).
3. Click the circle again to hide the bands.

> **Why it matters** — the flow only shows edges where the field's **value** genuinely travels; the string-match layer shows every **mention**. The gap between them is exactly where to look: a green line means "the flow explains this mention"; an amber line means "the name appears here, but no value flows" (or — rarely — a gap in the flow worth reporting).

---

## 8. Share a workspace

Workspaces are shared by **capability link**:

1. Open the workspace and copy the **`?ws=<id>`** URL (or the 32-character workspace id).
2. Send it to a colleague. They log in, paste the id into **"Open by workspace id…"**, and become a **read-only participant**: they can browse, search, and read every view — but cannot scan, re-index, or delete.
3. Removing the workspace from your own list removes only *your* link — not the workspace, not other participants' access.

---

## 9. Quick reference

| Action | Where |
|---|---|
| Upload scripts (zip) | Left panel → **Upload .zip** |
| Upload filter files | Left panel → **Filter** → **Upload filter** |
| Search a field | **Search** area → table + field → **Search** |
| Switch L1 ↔ L2 | View bar tabs at the top |
| Flow-only ↔ full view | View-mode selector in the graph toolbar |
| Walk the story | Field Story bar under the SQL panel — click a step chip |
| String-match diff | Field Story bar → the circle toggle; ◀/▶ to browse |
| Script lines | SQL panel — click anything in the graph to highlight its line |
| Open a shared workspace | **"Open by workspace id…"** → paste the `ws_id` |
| Log panel / History | Bottom / left-panel tabs |

---

## 10. Troubleshooting

| Symptom | Meaning | What to do |
|---|---|---|
| "Field … is not queried by any script" | The name resolves, but no script's flow carries it | Check the spelling/table; try the string-match layer to see every mention |
| Search returns scripts you didn't expect | Same-named columns exist on other tables | The resolved table is shown with the result — refine the table input |
| "Indexed … ago" is old | The index predates your latest upload | Re-open the workspace (the creator's open refreshes it) |
| A step chip highlights the same line as the previous one | The two steps genuinely anchor the same SQL line | — (both facts are on that line) |
| Green/amber bands don't move when toggling | The layer is show/hide — browse with ◀/▶ while it's on | — |
