# R31 — Multi-User Login: Implementation Blueprint

> Derived from the settled design `wiki/USER_IDENTITY_AND_WORKSPACE_EMAILS.md`
> (status: **design settled, all A-H1–A-H4 + A-M1–A-M10 confirmed and incorporated
> 2026-08-21, §10 ledger items 1–31**). This document is the file-level build plan —
> it converts the design into concrete modules, endpoints, data formats, and a
> build sequence. It does not restate locked decisions; it maps them to code.

## 0. Scope

**In scope (this build):** login gate, local accounts (`*@hsbc.com`, pre-provisioned from
CONFIG `PROVISIONED_USERS` — no admin HTTP endpoint, #269; PBKDF2), sessions (HttpOnly
cookie, ZERO expiry, #279), per-user "my workspaces" index + quota, role-dependent
remove-from-history (creator = physical delete w/ audit-before-removal; participant =
link removal), server-global `audit.json` + per-workspace `activity.json` (both O_APPEND
NDJSON), in-app notifications (**creator-driven only** — no visit memos/creator-alerts,
#285), `meta.json` `layouts` map + CAS-conditional state writes, single `PUT .../layout`
endpoint (**creator-only**, #272), one global heavy-op gate (#273), single uvicorn worker,
same-origin check.

**Out of scope / REMOVED by R31 backend fixes:** per-user **visit logging** (`open_visits`
registry, `visit_service.py`, visit memos — #285); the bare `DELETE /api/workspace`
cleanup-all endpoint + `cleanup_all_workspaces()` (#270); the `/api/admin` user-bootstrap
endpoint + `/api/admin` in `PUBLIC_API_PREFIXES` (#269); the 30-min idle session expiry
(#279); TLS (accepted residual risk, A-M7), email, self-service password recovery
(config re-provisioning only, #269), multi-worker support (documented misconfiguration,
A-M8). J12-11 cache reuse (#193) and the Final-L1 graph cache (#252) are
**IMPLEMENTED** (2026-08-24 — in-memory L1 caches in `l1_builder.py`; see R29.7/R29.8 in
`REQUIREMENTS_TRACEABILITY.md`).

## 1. Conflicts with the current code that MUST be resolved first

| # | Current behavior | Conflict | Resolution |
|---|------------------|----------|------------|
| C1 | `main.py` lifespan calls `cleanup_old_workspaces(24)` — deletes workspaces >24h old on every container start | Workspaces become **durable shared user data**; a 24h sweep destroys them | Remove the `cleanup_old_workspaces(24)` call and the `time`-based sweep from the lifespan. The R31 rollout migration (below) handles legacy cleanup once. |
| C2 | `workspace_service._WS_ID_RE = ^[0-9a-f]{12}$`; `ws_id = uuid4().hex[:12]` | Design A-H4 requires **full UUID4 / 128-bit**, no enumeration | `_WS_ID_RE = ^[0-9a-f]{32}$`; `ws_id = uuid4().hex` (32 hex). Touch **every** `_WS_ID_RE` consumer: `is_valid_ws_id`, `get_workspace`, `delete_workspace`, `create_workspace`. `uuid` already imported. |
| C3 | `create_workspace(zip_bytes)` writes `meta.json` = `{workspace_id, created_at, indexed, indexed_scripts}` | Needs `creator_username`, `state_version`, `layouts`, last-search state | Extend the meta schema (see §5). Keep existing keys; add new ones. |
| C4 | Frontend `AppShell.jsx` renders `DataFlowApp`/`App` with no auth | Design: login gate before every page | Add session check at AppShell mount → LoginPage / MyWorkspaces dashboard / app. See §7. |
| C5 | No heavy-op gate | Design §6: one global gate for search + `/analyze` + `/analyze_multi` | Add a single in-process gate (see §6.4). |

## 2. New backend modules

### 2.1 `backend/app/services/auth_service.py` — accounts, sessions

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
- `provision_user(username, password, force=False)` — **config-only** (#269): called by the
  startup provisioning loop (`main.py` lifespan) with `force=True` for every `PROVISIONED_USERS`
  entry; there is **no admin HTTP endpoint**. Returns False on invalid username/short password.
- `verify_username_format(username)` — `re.fullmatch(r".+@hsbc\.com")` (design: `*@hsbc.com`).
- `hash_password(password, salt=None)` — `hashlib.pbkdf2_hmac("sha256", password, salt, 100_000)`, 16-byte random salt hex.
- `login(username, password, ip)` → `token | None`; rejects unknown usernames (A-H2), records `last_login_ip`, creates session.
- `create_session(username, ip)` / `get_session(token)` / `destroy_session(token)` — **ZERO
  expiry (#279)**: no `last_active`, no idle reaper. `get_session` returns a copy or None.
- Sessions in-memory: `{token: {"username", "ip"}}`. Token = `secrets.token_hex(32)`.
- **NO open_visits** — per-user visit tracking is **dropped (#285)** (`visit_service.py` deleted);
  there is no `open_visit`/`touch_visit`/`flush_session_visits` machinery.

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
| `POST /api/auth/login` `{username, password}` | 200 + `Set-Cookie` session (HttpOnly, SameSite=Lax, **no max_age — ZERO expiry, #279**); 401 unknown username (A-H2) or bad password |
| `POST /api/auth/logout` | destroy session, clear cookie (no visit flush — #285) |
| `GET /api/auth/me` | current username + `last_login_ip`; 401 if none |
| `GET /api/workspaces` | my-workspaces index + `{count, cap}` |
| `GET /api/notifications` | current user's inbox |
| `POST /api/notifications/{id}/read` | mark read |

**REMOVED:** the gate-exempt `POST /api/admin/users` bootstrap endpoint (#269) — provisioning is
config-only (`PROVISIONED_USERS` force-synced at startup), so there is no HTTP way to create or
reset an account.

### 2.6 `backend/app/routers/workspace.py` — extend

| Endpoint | Contract |
|----------|----------|
| `POST /api/workspace` (existing upload) | + `creator_username` from session; quota check (409); full-UUID4 ws_id; stamps meta; adds to creator's index |
| `PUT /api/workspace/{ws_id}/layout` `{level:"l1"|"l2", script?, node_positions}` | A-M5 single endpoint → `meta.json.layouts` (key `l1` or `l2:{script}`); current-state only, replaces entry. **Creator-only (#272):** non-creator session → **403**. L2 keys persist (no opened_l2s prune) |
| `GET /api/workspace/{ws_id}/resume` | full current state: L1 + opened L2s + positions + `state_version` |
| `POST /api/workspace/{ws_id}/close` | **no-op returning 200** (#285 — visits dropped; kept so the frontend `closeWorkspace` control still works) |
| `GET /api/workspace/{ws_id}/activity` | read the history (name + IP + ts + action) |
| `DELETE /api/me/workspaces/{ws_id}` | role-dependent (A-M1/A-M2) — see §2.4 |
| `POST /api/workspace/{ws_id}/search`, `GET .../level1`, `GET .../level2` (existing) | behind the same session gate + heavy-op gate (search → 409 "system busy — please wait" while another heavy op runs, #273) |

**Removed:** the old `DELETE /api/workspace/{ws_id}` (A-M1 — single role-dependent path).
`DELETE /api/workspace` (cleanup-all) is **REMOVED entirely (#270)** — `cleanup_all_workspaces()`
deleted; no session can rmtree every workspace + notifications.

### 2.7 `backend/app/main.py` — gate, worker pin, migration

- **Login gate middleware**: every `/api/*` route except `/api/health` (and the static frontend) requires a valid session cookie → 401. Implement as a dependency applied at router registration (or `@app.middleware("http")` that checks the path prefix and cookie; static mount stays public but the SPA itself redirects to the login page).
  **#293 (2026-08-24)**: only the Data Flow Debugger needs login — the legacy analysis
  endpoints (`/api/analyze`, `/api/analyze_multi`, `/api/scripts`) are exempt via
  `PUBLIC_API_PREFIXES` (alongside `/api/health` and `/api/auth/login` — **`/api/admin/*`
  is REMOVED from the prefixes, #269**); SQL Analysis works logged-out. Caveat:
  `DELETE /api/scripts` (clears the analysis cache) also becomes public — accepted for an
  internal tool.
- **Config provisioning (#269)**: the lifespan force-syncs every `config.PROVISIONED_USERS`
  entry via `auth_service.provision_user(username, password, force=True)` — each deploy
  re-syncs accounts/passwords to config. No HTTP endpoint provisions users.
- **Same-origin check** (A-M7): on state-changing methods (POST/PUT/DELETE), verify `Origin`/`Referer` host == the service host; else 403. **#280 (decision only):** kept as defense-in-depth; the accepted no-`Origin`/`Origin: null` bypass is documented.
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
| `sessions` (in-memory) | `token → {username, ip}` | **ZERO expiry (#279)** — until logout or server restart (A-M9); browser drops the session cookie on close. No `open_visits` (dropped, #285) |

## 4. Visit lifecycle — DROPPED (#285)

Per-user **visit logging is removed entirely** — there is no open-visits registry, no
`visit_start`/`visit_end` activity entries, no visit memos/creator-alerts, and no flush on
workspace close / logout / expiry. `visit_service.py` is deleted. `POST /api/workspace/{ws_id}/close`
is a **no-op returning 200**. Only **creator-driven activity events** remain:
workspace **create**, **creator delete**, and **remove-from-my-history** (non-creator remove
records `removed-from-own-list` in the activity log; creator delete records `workspace deleted`
in the server-global audit log before removal). Those events drive the only notifications that
exist.

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
node ids that no longer exist are **skipped, not errors**; `l2:{script}` keys **persist once
saved** — the opened_l2s prune is removed (#272, also fixes #291). `views.json` stays
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
  **T8 (#295, 2026-08-24)** — the standalone `MyWorkspaces` dashboard is RETIRED and
  the dataflow tab ALWAYS renders `<DataFlowApp/>`: workspace management lives in a
  **"My workspaces" section at the top of the debugger's left panel** (list +
  📁 Select Folder + zip upload + open-by-id). `key={activeWsId}` remounts the
  debugger per open workspace; `?ws=` shared links opened logged-out open their
  workspace after login (unchanged).
- On mount: `GET /api/auth/me`.
  - 401 → the dataflow tab shows the **left-panel login form + center hint** (no blocking
    page); the analysis tab still works logged-out.
  - 200 + user's index → render **DataFlowApp** with the **"My workspaces" section**
    at the top of the debugger's left panel: list (role, last-opened, quota meter
    `{count}/{cap}`), per-row **Open** / **Remove** (creator → warning dialog "this
    physically deletes the workspace for everyone"; participant → light confirm),
    **workspace-id resume box**, notification bell (unread badge + inbox panel),
    **workspace upload** — both "📁 Select Folder" (webkitdirectory + JSZip client-side
    packing, mirroring the debugger's `WorkspacePanel.handleFolder`) and "+ Upload a
    folder (zip)". Upload → `api.uploadWorkspace(file)` → `onOpenWorkspace(result.workspace_id)`
    (no double-index). `WorkspacePanel` renders with `showUploads={false}` so only one
    pair of upload pickers exists.
  - Opening a workspace → the same `DataFlowApp` keeps the workspace open (the
    left-panel "My workspaces" section stays visible above the view tree).

  **#286 (2026-08-24)**: R31 released v3.3.162 with the dashboard **zip-only** — the
  webkitdirectory "Select Folder" picker lived only inside the debugger
  (`WorkspacePanel.jsx`), which requires an already-open workspace, so a fresh account
  (empty list) could never upload a folder (chicken-and-egg). Fixed by adding the
  folder picker to the dashboard's `MyWorkspaces.jsx`; deployed 2026-08-24.

  **#295 (2026-08-24, T8)**: the standalone dashboard is retired. `MyWorkspaces` is now
  an embedded **"My workspaces" section at the top of the debugger's left panel**
  (`DataFlowApp` renders `<MyWorkspaces open onOpen onUpload onRemove showUploads={false}/>`),
  and `AppShell` ALWAYS renders `DataFlowApp` when logged in (`key={activeWsId}` remounts
  per open workspace). The folder picker survives via that section, so a fresh account
  can still upload a folder — from inside the debugger.

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

1. **Foundation**: `auth_service.py` (users.json, sessions, config provisioning, hashing) + unit tests. (No visits — dropped, #285.)
2. **Logs**: `audit_service.py` (O_APPEND NDJSON) + tests (append-only, concurrent appends).
3. **Workspace service**: ws_id → 32 hex (C2), `meta.json` extension (C3), CAS write,
   role-dependent remove, quota, remove `cleanup_old_workspaces` (C1).
4. **Routers**: `auth.py` + workspace.py extensions; login-gate middleware; same-origin
   check; `--workers 1`; migration.
5. **Frontend**: LoginPage → MyWorkspaces → shell integration → debounced layout PUT →
   notifications/history/close → busy/409 handling.
6. **E2E**: login with a config-provisioned account, create/upload a workspace, search, open L2,
   drag, confirm layout persists on resume, second user id-open, participant remove vs creator
   delete (audit before removal), quota 409, layout PUT by a non-creator → 403 (#272).
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
  login gate will 401 it. The spec logs in with the **config default admin**
  (`admin@hsbc.com` / `123456`); the old force-provision `beforeAll` is removed (#269 —
  there is no `/api/admin` endpoint anymore).
- **Frontend size**: `AppShell` grows; keep the dashboard/components modular.
- **`cleanup_old_workspaces` removal**: confirm no other caller relies on the 24h sweep.
- **ws_id change breaks stored links/views from before rollout** — by design (migration
  removes legacy workspaces anyway).
- **Production gate default (deployed 3.3.162)**: `backend/start.py` sets
  `os.environ.setdefault("REQUIRE_LOGIN", "true")` — start.py IS the production entry
  (Dockerfile CMD `python3 -u start.py`). Dev uses Dockerfile.dev's `uvicorn --reload`,
  which never runs start.py, so the gate stays OFF in dev. An explicit
  `REQUIRE_LOGIN=0/1` in the run environment still wins (setdefault).
- **Provisioning is config-only (#269)**: `config.PROVISIONED_USERS` (default
  `admin@hsbc.com` / `123456`, env override `PROVISIONED_USERS_JSON`) is force-synced at
  startup. There is **no HTTP endpoint** that creates or resets accounts, so the old
  gate-exempt `/api/admin` bootstrap hole is gone. Each deploy re-syncs passwords to
  config (a drifted password is overwritten back to the config value).
- **Durable user data across deploys**: `target_deploy.sh` mounts the named volume
  `gps_workspace_data:/tmp/workspaces` on both the start and rollback `docker run`s.
  Workspaces + `users.json` survive container recreation. A rollback to a pre-R31
  image would leave the mounted dir untouched (the old image just ignores it).
