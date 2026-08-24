# R31 — Multi-User Login: Implementation Blueprint

> Derived from the settled design `wiki/USER_IDENTITY_AND_WORKSPACE_EMAILS.md`
> (status: **design settled, all A-H1–A-H4 + A-M1–A-M10 confirmed and incorporated
> 2026-08-21, §10 ledger items 1–31**). This document is the file-level build plan —
> it converts the design into concrete modules, endpoints, data formats, and a
> build sequence. It does not restate locked decisions; it maps them to code.

## 0. Scope

**In scope (this build):** login gate, local accounts (`*@hsbc.com`, pre-provisioned
allowlist, PBKDF2), sessions (HttpOnly cookie, 30-min idle), open-visits registry,
per-user "my workspaces" index + quota, role-dependent remove-from-history (creator =
physical delete w/ audit-before-removal; participant = link removal), server-global
`audit.json` + per-workspace `activity.json` (both O_APPEND NDJSON), in-app
notifications, `meta.json` `layouts` map + CAS-conditional state writes, single
`PUT .../layout` endpoint, single uvicorn worker, same-origin check.

**Out of scope:** TLS (accepted residual risk, A-M7), email, self-service password
recovery (admin-mediated only, A-H1), multi-worker support (documented
misconfiguration, A-M8), J12-11 cache reuse (still trigger-gated, #193), Final-L1
graph cache (still deferred, #252).

## 1. Conflicts with the current code that MUST be resolved first

| # | Current behavior | Conflict | Resolution |
|---|------------------|----------|------------|
| C1 | `main.py` lifespan calls `cleanup_old_workspaces(24)` — deletes workspaces >24h old on every container start | Workspaces become **durable shared user data**; a 24h sweep destroys them | Remove the `cleanup_old_workspaces(24)` call and the `time`-based sweep from the lifespan. The R31 rollout migration (below) handles legacy cleanup once. |
| C2 | `workspace_service._WS_ID_RE = ^[0-9a-f]{12}$`; `ws_id = uuid4().hex[:12]` | Design A-H4 requires **full UUID4 / 128-bit**, no enumeration | `_WS_ID_RE = ^[0-9a-f]{32}$`; `ws_id = uuid4().hex` (32 hex). Touch **every** `_WS_ID_RE` consumer: `is_valid_ws_id`, `get_workspace`, `delete_workspace`, `create_workspace`. `uuid` already imported. |
| C3 | `create_workspace(zip_bytes)` writes `meta.json` = `{workspace_id, created_at, indexed, indexed_scripts}` | Needs `creator_username`, `state_version`, `layouts`, last-search state | Extend the meta schema (see §5). Keep existing keys; add new ones. |
| C4 | Frontend `AppShell.jsx` renders `DataFlowApp`/`App` with no auth | Design: login gate before every page | Add session check at AppShell mount → LoginPage / MyWorkspaces dashboard / app. See §7. |
| C5 | No heavy-op gate | Design §6: one global gate for search + `/analyze` + `/analyze_multi` | Add a single in-process gate (see §6.4). |

## 2. New backend modules

### 2.1 `backend/app/services/auth_service.py` — accounts, sessions, visits

**users.json** (durable, `WORKSPACE_ROOT/users.json`):

```json
{
  "alice@hsbc.com": {
    "salt": "<hex>",
    "password_hash": "<hex pbkdf2>",
    "created_at": "ISO",
    "last_login_ip": "1.2.3.4",
    "workspaces": [
      {"ws_id": "<32hex>", "role": "creator|participant", "first_opened": "ISO", "last_opened": "ISO"}
    ]
  }
}
```

- `load_users()` / `save_users(users)` — temp+rename (accepted-loss, A-M3/§6.3).
- `provision_user(username, password)` — allowlist only (called by admin endpoint).
- `verify_username_format(username)` — `re.fullmatch(r".+@hsbc\.com")` (design: `*@hsbc.com`).
- `hash_password(password, salt=None)` — `hashlib.pbkdf2_hmac("sha256", password, salt, 100_000)`, 16-byte random salt hex.
- `login(username, password, ip)` → `token | None`; rejects unknown usernames (A-H2), records `last_login_ip`, creates session.
- `create_session(username, ip)` / `get_session(token)` (extends `last_active`, 30-min idle) / `destroy_session(token)`.
- Sessions in-memory: `{token: {"username", "ip", "last_active"}}`. Token = `secrets.token_hex(32)`.
- **open_visits**: `{token: {ws_id: {"opened_at", "last_active"}}}`; helpers `open_visit(token, ws_id)`, `touch_visit(token, ws_id)`, `flush_session_visits(token)`.
- `flush_session_visits(token)` → for each open ws_id: write activity-log visit-end, create memo (+ creator alert) **only if no other session of the same username has that ws_id open** (A-M10). See §4.

### 2.2 `backend/app/services/audit_service.py` — append-only logs

- `append_activity(ws_id, username, ip, action, detail)` — open `WORKSPACE_ROOT/{ws_id}/activity.json` with `os.open(..., O_APPEND|O_CREAT|O_WRONLY)`, write one NDJSON line `{username, ip, ts, action, detail}`. Real append — no read-modify-write (A-M3).
- `append_audit(username, ip, ws_id, action)` — same, to `WORKSPACE_ROOT/audit.json` (server-global, survives the workspace it describes, A-H3).
- `read_activity(ws_id)` → list of parsed records (for the history panel).

### 2.3 `backend/app/services/notification_service.py`

- `notifications/{username}.json` → `[{id, kind: "memo"|"alert", title, body, read, created_at}]`, kept forever.
- `add_notification(username, kind, title, body)`; `list_notifications(username)`; `mark_read(username, id)`.
- Title format: `[SQL Data Flow Visualizer] Workspace {ws_id} · {YYYY-MM-DD HH:MM}`.

### 2.4 `backend/app/services/workspace_service.py` — extend (see C2/C3)

- `_WS_ID_RE` → 32 hex; `create_workspace(zip_bytes, creator_username)` → full uuid4, `meta.json` += `creator_username`, `created_at`, `state_version: 0`, `layouts: {}`, `last_search: null`, `opened_l2s: []`.
- `read_meta(ws_id)` / `write_meta_cas(ws_id, meta, expected_state_version)` → CAS (single worker makes check+rename atomic, A-M8): apply only if stored `state_version == expected`; bump `state_version`; else return the fresh meta for the 409 flow.
- `remove_from_my_history(ws_id, username, ip)` → **role-dependent (A-M2)**:
  - creator → `append_audit(...)` **first** (A-H3), `shutil.rmtree(ws_dir)`, drop from **every** user's index in users.json.
  - participant → drop from caller's index only; `append_activity(ws_id, ..., "removed-from-own-list")`.
- **Quota** `MAX_WORKSPACES_PER_USER = 10` (single config constant, `app/config.py`): `index_has_room(username)` → `len(workspaces) < 10`; else 409 "remove one from your list first".

### 2.5 `backend/app/routers/auth.py` (new)

| Endpoint | Contract |
|----------|----------|
| `POST /api/auth/login` `{username, password}` | 200 + `Set-Cookie` session (HttpOnly, SameSite=Lax); 401 unknown username (A-H2) or bad password |
| `POST /api/auth/logout` | destroy session, `flush_session_visits`, clear cookie |
| `GET /api/auth/me` | current username + `last_login_ip`; 401 if none |
| `POST /api/admin/users` `{username, password}` | admin-only (config `ADMIN_USERNAME`, default first provisioned user); creates/resets password (A-H1). Rejects non-`@hsbc.com`, short password |
| `GET /api/workspaces` | my-workspaces index + `{count, cap}` |
| `GET /api/notifications` | current user's inbox |
| `POST /api/notifications/{id}/read` | mark read |

### 2.6 `backend/app/routers/workspace.py` — extend

| Endpoint | Contract |
|----------|----------|
| `POST /api/workspace` (existing upload) | + `creator_username` from session; quota check (409); full-UUID4 ws_id; stamps meta; adds to creator's index |
| `PUT /api/workspace/{ws_id}/layout` `{level:"l1"|"l2", script?, node_positions}` | A-M5 single endpoint → `meta.json.layouts` (key `l1` or `l2:{script}`); current-state only, replaces entry |
| `GET /api/workspace/{ws_id}/resume` | full current state: L1 + opened L2s + positions + `state_version` |
| `POST /api/workspace/{ws_id}/close` | end visit → activity log + memo (+ creator alert) |
| `GET /api/workspace/{ws_id}/activity` | read the history (name + IP + ts + action) |
| `DELETE /api/me/workspaces/{ws_id}` | role-dependent (A-M1/A-M2) — see §2.4 |
| `GET /api/workspace/{ws_id}/search`, `GET .../level1`, `GET .../level2` (existing) | behind the same session gate + heavy-op gate; record visit touch + activity |

**Removed:** the old `DELETE /api/workspace/{ws_id}` (A-M1 — single role-dependent path).
`DELETE /api/workspace` (cleanup-all) becomes admin-only or is removed.

### 2.7 `backend/app/main.py` — gate, worker pin, migration

- **Login gate middleware**: every `/api/*` route except `/api/health` (and the static frontend) requires a valid session cookie → 401. Implement as a dependency applied at router registration (or `@app.middleware("http")` that checks the path prefix and cookie; static mount stays public but the SPA itself redirects to the login page).
  **#293 (2026-08-24)**: only the Data Flow Debugger needs login — the legacy analysis
  endpoints (`/api/analyze`, `/api/analyze_multi`, `/api/scripts`) are exempt via
  `PUBLIC_API_PREFIXES` (alongside `/api/health`, `/api/auth/login`, `/api/admin/*`);
  SQL Analysis works logged-out. Caveat: `DELETE /api/scripts` (clears the analysis
  cache) also becomes public — accepted for an internal tool.
- **Same-origin check** (A-M7): on state-changing methods (POST/PUT/DELETE), verify `Origin`/`Referer` host == the service host; else 403.
- **Single worker**: the run command / Dockerfile CMD pins `--workers 1` (A-M8). Document that multi-worker is a misconfiguration.
- **Migration at rollout** (design §6): delete legacy workspaces without `creator_username` (user-confirmed, no backup); remove the 24h auto-cleanup (C1); write a startup note when the audit.log is first created.

## 3. Data formats (design §6, locked)

| Store | Format | Writes |
|-------|--------|--------|
| `users.json` | one JSON object, username-keyed | temp+rename, accepted-loss |
| `notifications/{username}.json` | JSON array | temp+rename, accepted-loss |
| `workspaces/{ws_id}/meta.json` | JSON; `creator_username`, `created_at`, `state_version`, `last_search`, `opened_l2s`, `layouts` | **CAS-gated** temp+rename (A-M4) |
| `workspaces/{ws_id}/activity.json` | NDJSON, one record/line | **O_APPEND** (A-M3) |
| `WORKSPACE_ROOT/audit.json` | NDJSON, one record/line | **O_APPEND** (A-M3), global |
| `sessions`, `open_visits` | in-memory dicts | lost on restart — **accepted** (A-M9) |

## 4. Visit lifecycle (A-M10, one memo per user)

```
open workspace (via index open / id resume / create)
  → open_visits[token][ws_id] = {opened_at, last_active}
  → activity.json: {username, ip, ts, "visit_start"}
workspace close / logout / idle-expiry (per session only)
  → activity.json: {"visit_end"}
  → memo to visitor: username (self-describing), ws_id, visit window,
    session login time + IP, script names + count, last search, L2s opened, layout saves
  → creator alert (if visitor != creator): who, when, what changed
  → memo/alert created ONLY if no other session of that username has ws_id open
```

## 5. `meta.json` schema (extended)

```json
{
  "workspace_id": "<32hex>",
  "creator_username": "alice@hsbc.com",
  "created_at": "ISO",
  "state_version": 0,
  "indexed": false,
  "indexed_scripts": [],
  "last_search": null,
  "opened_l2s": [],
  "layouts": {}
}
```

`layouts` keys: `"l1"` and `"l2:{script_name}"` → `{node_id: [x, y]}`. Positions for
node ids that no longer exist are **skipped, not errors**; stale `l2:{script}` keys for
un-reopened L2s are dropped (retention rule, design §4 Q4). `views.json` stays
search-view records only — **not** layout storage (A-M5).

## 6. Concurrency & gating

### 6.1 CAS state writes (A-M4)
Every state save carries the `state_version` the client last loaded. Server applies
only if it matches; else returns `409 {detail, fresh_state, state_version}`. Client
auto-reloads, re-applies its pending edit, shows "state changed by X at HH:MM — refreshed".

### 6.2 Debounced saves (user-confirmed 2026-08-21)
Frontend PUTs layout ≤1/s (coalescing drags) + a final PUT on close. Conflicts stay
rare by construction.

### 6.3 Accepted-loss files (A-M3/§6)
`users.json` + `notifications/{username}.json`: last-writer-wins temp+rename. Never
corrupts; may drop a concurrent write. Accepted (low simultaneous users, single worker).

### 6.4 Heavy-op gate (design §6)
One global in-process gate: debugger search + `/analyze` + `/analyze_multi`. While one
runs, a new one → `409 "system busy — please wait"`. Use an `asyncio`/threading gate in
`app/services/heavy_gate.py` with a context manager.

## 7. Frontend

### 7.1 Session-aware shell (`AppShell.jsx`)
- **No full-screen gate (2026-08-24, #293)**: the `!me → <LoginPage/>` gate is removed.
  The top bar with the mode tabs (**Data Flow Debugger** / **SQL Analysis**) is **always
  visible**, logged in or out. In the dataflow tab an unauthenticated user sees the
  debugger shell layout with only the login form in the **left panel** (a `.panel-left`
  `<LoginForm/>`) and a one-line hint in the center (`.empty-state`
  "Sign in to use the Data Flow Debugger"); nothing else in the dataflow tab is usable
  logged-out. The **SQL Analysis** tab renders `App.jsx` with **no login** (only the
  Data Flow Debugger needs login — legacy `/api/analyze`, `/api/analyze_multi`,
  `/api/scripts` are exempt from the `login_gate` middleware, §2.7). Logged in:
  unchanged — `MyWorkspaces` dashboard (no workspace open) or `DataFlowApp` (workspace
  open); a `?ws=` shared link opened logged-out opens its workspace after login.
- On mount: `GET /api/auth/me`.
  - 401 → the dataflow tab shows the **left-panel login form + center hint** (no blocking
    page); the analysis tab still works logged-out.
  - 200 + user's index → render **MyWorkspaces dashboard**: list (role, last-opened,
    quota meter `{count}/{cap}`), per-row **Open** / **Remove** (creator → warning dialog
    "this physically deletes the workspace for everyone"; participant → light confirm),
    **workspace-id resume box**, notification bell (unread badge + inbox panel),
    **workspace upload** — both "📁 Select Folder" (webkitdirectory + JSZip client-side
    packing, mirroring the debugger's `WorkspacePanel.handleFolder`) and "+ Upload a
    folder (zip)".
  - Opening a workspace → render the existing `DataFlowApp`/`App`.

  **#286 (2026-08-24)**: R31 released v3.3.162 with the dashboard **zip-only** — the
  webkitdirectory "Select Folder" picker lived only inside the debugger
  (`WorkspacePanel.jsx`), which requires an already-open workspace, so a fresh account
  (empty list) could never upload a folder (chicken-and-egg). Fixed by adding the
  folder picker to the dashboard's `MyWorkspaces.jsx`; deployed 2026-08-24.

### 7.2 New components
- `frontend/src/components/LoginForm.jsx` (form-only, embedded in the debugger's left
  panel — extracted from the deleted `LoginPage.jsx`; keeps the Playwright selectors:
  a `<form>`, username `you@hsbc.com`, one `input[type="password"]`, "Sign in")
- `frontend/src/components/MyWorkspaces.jsx` (dashboard + quota meter + remove dialogs + resume box)
- `frontend/src/components/NotificationBell.jsx` (unread badge, inbox, mark-read)
- `frontend/src/components/HistoryPanel.jsx` (activity log viewer)
- `frontend/src/components/CloseWorkspace.jsx` (visit-end trigger) — or a button in the existing header.

### 7.3 DataFlowApp / App integration
- Wrap API calls with the session cookie (same-origin, `fetch` sends it automatically).
- `PUT /api/workspace/{ws_id}/layout` — debounced ≤1/s on drag-end + final on close;
  silent-fail handling.
- "state changed by X" toast on 409 → reload + re-apply.
- "System busy — please wait" on search 409; re-enable when the gate frees.
- Opened-L2 strip under the L1 nav: saved L2s clickable; un-saved L2 recomputes fresh.
- Close workspace control in the header.

## 8. Build sequence

1. **Foundation**: `auth_service.py` (users.json, sessions, visits, hashing) + unit tests.
2. **Logs**: `audit_service.py` (O_APPEND NDJSON) + tests (append-only, concurrent appends).
3. **Workspace service**: ws_id → 32 hex (C2), `meta.json` extension (C3), CAS write,
   role-dependent remove, quota, remove `cleanup_old_workspaces` (C1).
4. **Routers**: `auth.py` + workspace.py extensions; login-gate middleware; same-origin
   check; `--workers 1`; migration.
5. **Frontend**: LoginPage → MyWorkspaces → shell integration → debounced layout PUT →
   notifications/history/close → busy/409 handling.
6. **E2E**: provision a user, login, create/upload a workspace, search, open L2, drag,
   confirm layout persists on resume, second user id-open + alert, participant remove
   vs creator delete (audit before removal), quota 409.
7. **Gate**: full pytest suite (existing 871 must stay green) + Jaccard gate 16/16 +
   vitest + playwright 6/6, then release → deploy → push.

## 9. Verification checklist (gate before release)

- [ ] `docker exec gps-sql-backend python3 -m pytest tests/test_jaccard_benchmark.py -q` → 16 passed, floors 1.0000
- [ ] full backend suite: 871 passed / 5 skipped (plus new R31 tests)
- [ ] `cd frontend && ./node_modules/.bin/vitest run` → all green
- [ ] playwright 6/6 (tests/playwright/dataflow.spec.js) — must be updated if login gate breaks the harness (the spec logs in first)
- [ ] migration ran once: legacy workspaces removed, audit.log created
- [ ] `docker compose` runs with `--workers 1` (no multi-worker drift)

## 10. Risks / notes

- **Playwright spec**: the current `dataflow.spec.js` goes straight to the app. The
  login gate will 401 it. The spec must provision a test user + login first (or run
  behind the gate via the login flow). Plan for this explicitly.
- **Frontend size**: `AppShell` grows; keep the dashboard/components modular.
- **`cleanup_old_workspaces` removal**: confirm no other caller relies on the 24h sweep.
- **ws_id change breaks stored links/views from before rollout** — by design (migration
  removes legacy workspaces anyway).
- **Production gate default (deployed 3.3.162)**: `backend/start.py` sets
  `os.environ.setdefault("REQUIRE_LOGIN", "true")` — start.py IS the production entry
  (Dockerfile CMD `python3 -u start.py`). Dev uses Dockerfile.dev's `uvicorn --reload`,
  which never runs start.py, so the gate stays OFF in dev. An explicit
  `REQUIRE_LOGIN=0/1` in the run environment still wins (setdefault).
- **Admin-endpoint bootstrap hole**: `/api/admin/*` is exempt from the login gate —
  the only HTTP way to provision the FIRST account on a fresh deploy ("default first
  provisioned user", §2.5). It only ever targets `ADMIN_USERNAME` (403 otherwise).
  The playwright `beforeAll` uses it with `force=true` (idempotent; users.json persists).
  LAN exposure is consistent with A-M7's accepted plain-HTTP-on-LAN residual risk.
- **Durable user data across deploys**: `target_deploy.sh` mounts the named volume
  `gps_workspace_data:/tmp/workspaces` on both the start and rollback `docker run`s.
  Workspaces + `users.json` survive container recreation. A rollback to a pre-R31
  image would leave the mounted dir untouched (the old image just ignores it).
