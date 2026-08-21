# User Identity & Workspace Collaboration — Local Accounts (no email)

## Status

> **Design settled 2026-08-19 — implementation awaiting the go-command; NOT implemented in any
> release (no code exists).** Traceability rows **R31.1–R31.13** live in
> `wiki/REQUIREMENTS_TRACEABILITY.md`. `wiki/CODE_REVIEW_2026-08-19.md` (Part A, read-only) flagged
> High-severity design flaws; all four were **resolved and incorporated 2026-08-21**:
> **A-H1** → admin-mediated password reset only (self-service re-register removed); **A-H2** →
> pre-provisioned allowlist accounts (unknown usernames rejected at login); **A-H3** → creator
> delete recorded in a **server-global audit log before removal**, non-creator remove-from-list
> recorded in the workspace's activity log; **A-H4** → `ws_id` is server-generated **UUID4** with
> **no listing endpoint**. Medium findings **A-M1–A-M10** are under one-by-one confirmation;
> **A-M1–A-M6 resolved 2026-08-21** (A-M1 single role-dependent `DELETE /api/me/workspaces/{ws_id}`;
> A-M2 history cap = creation cap; A-M3 O_APPEND NDJSON audit logs; A-M4 CAS-conditional state
> writes + debounced saves; A-M5 `meta.json` `layouts` map + single `PUT .../layout` endpoint;
> A-M6 `POST /api/workspace` create = extended folder upload; A-M7 `SameSite=Lax` + same-origin
> check + HTTP residual risk documented; A-M8 single uvicorn worker enforced; A-M9 restart loses
> open-visit flush accepted; A-M10 open_visits keyed by session, username in memos).
> **All A-M items resolved 2026-08-21.**

> Design note — revised 2026-08-19 (6th revision). Email is **dropped** (no usable
> mail path on the target network). Replaced with **local accounts (`@hsbc.com` usernames) + IP
> audit + in-app notifications + per-workspace activity log + a per-user "my workspaces" index**.
> **All decisions locked — design settled, awaiting the go-command to implement. No code changed.**

**Change vs the 2026-08-14 email design:** every email function maps to an in-app equivalent —
OTP login → local accounts; memo/creator-alert emails → notification inboxes; mailbox-searchable
titles → notification-card titles. **Added later revisions:** `@hsbc.com`-enforced usernames,
per-operation **username + IP** recording, a per-user workspace index on login, and a
**role-dependent remove-from-my-history** workspace lifecycle (creator = physical delete with
warning, participant = link removal only) + **quota** (A-M2, 2026-08-21).

## 1. Purpose

Make the SQL Data Flow Visualizer a multi-user service where:

1. **A login entrance page gates every page of the service** — no page is reachable before login.
   Users log in with their HSBC-postfix email **`user_name@hsbc.com`** (format enforced, validated
   as `*@hsbc.com`) plus a **password issued when the account is provisioned**. Accounts are
   **pre-provisioned from an admin-managed allowlist** — an unknown username is rejected at login,
   never auto-created. The email string is an identifier only — **no mail is ever sent**.
2. Every operation on a workspace is **recorded with the actor's name and IP**, so "who modified
   this" is always answerable.
3. Work is organized by **workspace id** — the shared unit of state. A workspace keeps its own
   **history** and can be opened by its id.
4. **Under each user account** the list of workspaces the user has worked on is kept; on login the
   user picks one, and can **read the workspace's history**.
5. Resuming a workspace restores the full current state **including manually-adjusted L1/L2
   layouts** — the layout work is the user's main contribution and must survive.

Environment: the target machine is on a strictly managed network — **no internet, and no usable
mail path** (verified 2026-08-14: no mailer binaries, no mail configs, no SMTP ports). Everything
lives inside the deployed web app.

## 2. Model at a glance (user-confirmed 2026-08-19)

- **Two parallel entities: the user account and the workspace.**
  - **User account** = identity (`user_name@hsbc.com` + password) + own notification inbox + own
    workspace index. **Pre-provisioned** from the admin-managed allowlist before first login.
  - **Workspace** = own id + **shared current state** + readable **history** (activity log).
- **Account ↔ workspace is 1:N.** A user may create or visit many workspaces.
- **"My workspaces" (per-user index, personal):** the list of workspaces the user has **created or
  visited** (role: creator/participant, last-opened time). Shown on login so the user can choose one.
- **Workspace current state (shared, not personal):** one L1 (the last search) + the opened L2s
  with saved layouts. Anyone who opens the workspace by id sees **this same current state**;
  the applied write wins (CAS-conditional, A-M4). This is **not** a per-user search-history list.
- **Workspace history (readable by any opener):** the per-workspace **activity log** — who (name +
  IP) did what, when. This is what "he can read the history of this workspace" means.

The earlier ambiguity is settled: "personal" applies to the **workspace index under an account**;
the workspace's **search state** stays shared and current-state-only.

## 3. Sharing model (how users share a workspace)

- Users share by exchanging the **workspace id** — or simply a link
  `http://192.168.0.66:8000/…?ws={ws_id}`. Any **logged-in** user who knows the id can open and
  edit it. No email, no external channel required. **`ws_id` is server-generated, high-entropy
  (UUID4 / 128-bit random)** — never client-supplied, never sequential — and **no endpoint lists
  workspace ids**; the only ways in are one's own index, an explicit shared id/link, or an id the
  user was given (A-H4).
- The workspace records its **creator** (username) at creation. When someone else works on it, the
  creator is **alerted in-app** (next login).
- Every operation writes to the workspace's **activity log** with the actor's **username + IP** —
  the shared audit trail.

## 4. Agreed decisions (Q&A summary)

| # | Question | Decision |
|---|----------|----------|
| — | Login | **Username MUST be `*@hsbc.com`** (format-validated) + **password**. Accounts are **pre-provisioned from the admin allowlist**; an unknown username is **rejected** at login (no self-registration). Client **IP recorded at login** and on every workspace operation. No email, no OTP. |
| — | Logout | **Idle timeout (30 min)**; also a logout button. Visit flush triggers: workspace close / session expiry / logout. |
| — | One L1 + multiple L2 | Keep. One search = one L1; the L2s the user opened are retained. |
| Q2 | Last-search state | **Shared**, workspace-wide. Resume = current workspace state, never personal history. Last-writer (closes last) wins. |
| Q3 | Access model | **Open by workspace id** — any logged-in user who knows the id can open and edit; creator is only alerted (in-app). (Known simple, slight risk, accepted for now.) |
| Q4 | Layout save | **L1 and L2 node x/y are both autosaved** on each drag-end. Only the L2 views the user actually **opened** are retained. Save **node x/y only**; zoom/pan ignored. **One storage location** — `meta.json` `layouts` map (A-M5). |
| — | Multiple tabs | A user may have several workspaces open in different tabs **and in several sessions (browsers)**. Visits are tracked **per session, per workspace** (A-M10); logout/expiry flushes **only that session's** visits; memos are aggregated per user (created when the last of the user's sessions closes the workspace). |
| — | Login gate | **Login entrance page before any page** — the whole service is behind it; only the health endpoint stays public. |
| Q5 | Concurrent users | **CAS-conditional saves** (A-M4): a save applies only if the `state_version` it was built on still matches; otherwise **409 → auto reload + re-apply** with a "state changed by X — refreshed" notice. Saves are **debounced (≤1/s + final on close)** so rapid operations coalesce and conflict windows stay rare. No locking. |
| Q6 | Accounts | **Persisted local accounts** (pre-provisioned from the admin allowlist + password issued at provisioning). Stable identity is what makes the inbox, the per-user index, and "creator" meaningful. |
| Q7 | Notifications | **In-app, keep all records, one file per user** (`notifications/{username}.json`). One memo per workspace-close. **No script contents** — script names, search table/field names, ws_id, time. Enough to understand what happened. |
| Q8 | Idle timeout | **30 minutes**. Memo added on workspace close / session expiry / logout. |
| — | Concurrent writes | **Accepted**: losing the rarer concurrent update is OK (low simultaneous-user count). Files are still written atomically (temp + rename) so a race **never corrupts a file** — it only drops the losing writer's update. |
| — | Layout write cadence | Frontend writes layout **at most once per second**; a **final write on workspace close**. The layout file keeps **only current state** (per-view `{node_id:[x,y]}`), never history — its size does not grow. |
| — | Heavy CPU load | **One global heavy-op gate** covering the debugger **search** and the analysis API (`/analyze`, `/analyze_multi`). While any one is running, a new one is **refused with "system busy — please wait"** instead of starting in parallel and blocking the server. |
| — | IP audit | **Every workspace operation recorded as {username, ip, ts, action, detail}** — "who modified this" is always answerable. |
| — | Workspace delete | **One action, role-dependent (A-M2).** A creator's **remove-from-my-history IS the physical delete** (pop-up warning; server-global audit log written **before** removal; dropped from every index). A non-creator's remove-from-my-history only drops the link from their own index — the workspace and files survive, logged in the workspace's activity log. No separate delete path. |
| — | Quota | Each user may **keep at most `MAX_WORKSPACES_PER_USER`** workspaces in their "my workspaces" list (default **10**, single config constant). Because a creator's remove-from-history is a **physical delete**, **a creator can never hold more than 10 of their own workspaces** — each creation occupies a slot; to create more they must delete one (A-M2). At the cap, opening a new workspace (create or id-open) requires removing one from the list first. |
| — | Password recovery | **Admin-mediated reset only.** The user contacts an administrator, who verifies identity out-of-band and issues a new password. **No self-service path ever overwrites an existing identity** (A-H1). |
| — | Old workspaces | **Removed** at rollout — pre-feature workspaces (no creator) are deleted; all workspaces from this point carry a creator. |

## 5. Model

### 5.1 Identity & login (local accounts)

- Login page: **username (must match `*@hsbc.com`) + password**. An unknown username is
  **rejected** — accounts exist only when **pre-provisioned from the admin-managed allowlist**
  (no self-registration); `created_at` records provisioning time.
- Format validation on the server: the username must match `*@hsbc.com`. It is **never** used as a
  mailbox — no mail is sent anywhere.
- Passwords hashed with a salted KDF (PBKDF2-HMAC via stdlib `hashlib`; no new dependencies).
  Never stored or logged in plaintext. Minimum length **≥ 6**.
- **Password recovery = admin-mediated reset.** There is **no self-service "forgot password"**:
  the user contacts an administrator, who verifies identity out-of-band and sets a new password.
  **No endpoint ever overwrites an existing identity without such verification** (A-H1).
- The client **IP** is captured at login (`request.client.host`), stored on the session and on the
  user record (`last_login_ip`), and included in the visit's audit entries.
- Successful login creates a **session**; identity is an `HttpOnly` + `SameSite=Lax` cookie (A-M7).

### 5.2 Sessions & open visits

- Server-side sessions keyed by an opaque token in an `HttpOnly` cookie (not readable by JS),
  holding `{username, ip, last_active}`. Cookie set with **`SameSite=Lax`** — cross-site requests
  never carry it (A-M7).
- **Open-visits registry (per SESSION, per workspace):** `session_token → {ws_id → {opened_at,
  last_active}}`; the session record carries **`username`** (A-M10). A user may have several
  workspaces open at once (multiple tabs) **and** several simultaneous sessions (multiple
  browsers); each is an independent visit keyed to its own session.
- **Idle timeout 30 min** — activity extends it; on expiry the session is destroyed and **only
  that session's** open visits flush (one memo per workspace + creator alerts where applicable).
  A long-running search that completes extends the session (it counts as activity).
- Explicit **logout** button ends the session immediately (same flush — only that session's visits).
- **Per-user aggregation (A-M10):** when a session closes a visit, the memo/creator-alert is
  created **only if no other of that user's sessions still has the workspace open** — two sessions
  on the same workspace produce one memo when the *last* one closes; one browser's logout never
  closes another browser's visit.
- Session store and `open_visits` are in-memory; both are lost on container restart — **accepted**
  (A-M9). A restart interrupts any open visit **silently**: no visit-end memo for that stretch and
  no creator alert. On next login the user simply continues; the interrupted visit's bookkeeping is
  skipped.

### 5.3 Workspace state (shared, durable)

- A workspace = `WORKSPACE_ROOT/{ws_id}/` (existing) plus **`meta.json`**:
  - `creator_username` (fixed at creation)
  - `created_at`
  - a **`state_version`** (incremented on every applied state write — drives the concurrent-editing
    notice; **CAS-conditional writes** make it genuinely monotonic, A-M4)
  - the **last search state**: exactly one L1 (the search) + the list of **opened L2 views** —
    **both the L1 and each opened L2 carry persisted node x/y layouts**
- **Last search is shared and current-state-only.** A new search by anyone replaces the stored one.
  Resume by ws_id shows the current state, not history.
- **State writes are CAS-conditional, not blind last-writer-wins (A-M4):** every save carries the
  `state_version` the client last loaded; the server applies it **only if it still matches** the
  stored version, else replies **409 "state changed by X at HH:MM — refreshed"**. The client then
  reloads the fresh state and **re-applies the edit on top of it** automatically. No locking.
- **Debounced saves keep conflicts rare (user-confirmed 2026-08-21):** the frontend auto-saves at
  **most once per second** (accumulated operations coalesce into one save) plus a **final save on
  workspace close** — so each user offers at most ~1 conflict window per second, not one per drag.
- **Concurrent-editing notice:** on a 409 the client shows "state changed by X at HH:MM — refreshed"
  and re-renders after re-applying its pending edit; it also fires when a loaded `state_version` is
  newer than what the user last had on screen.
- **Layout persistence — ONE storage location (A-M5):** all node x/y lives in a single `layouts`
  map inside `meta.json`: `{"l1": {node_id:[x,y]}, "l2:{script}": {node_id:[x,y]}, …}` — `l1` for
  the cross-script graph, `l2:{script_name}` per opened L2 (unique within the workspace's single
  current search). `views.json` stays search-view records only and is **not** layout storage.
- The frontend reports node x/y **≤1/s while dragging** plus a **final write on workspace close**
  (§4 Q4 / §10.18 — the debounce also minimizes A-M4 CAS conflict windows), via a **single
  endpoint** `PUT /api/workspace/{ws_id}/layout` `{level: "l1"|"l2", script?, node_positions}`.
  Each entry is **current state only** (replaced on save, never appended — file size does not
  grow). On resume, positions are re-applied instead of recomputed; **positions for node ids that
  no longer exist are skipped, not errors**; stale `l2:{script}` keys for L2s not re-opened are
  dropped (retention rule, §4 Q4). Zoom/pan intentionally not saved. (History of layout *actions*
  lives in the activity log, not the layout file.)

### 5.4 Activity log + in-app notifications

**Activity log (per workspace, append-only)** — `workspaces/{ws_id}/activity.json`, stored as
**NDJSON: one `{...}` record per line, appended with `O_APPEND`** — real appends, never
read-modify-write, so concurrent appends are never lost (A-M3). Every entry is
`{username, ip, ts, action, detail}`. Events include: visit start, search performed, L2 opened,
layout saved, visit end, **remove-from-my-list**. This is the durable, IP-audited "who modified
this" record, readable by any opener. **The creator's physical DELETE is NOT logged here** — this
file is removed with the workspace, so the deletion event is written to the **server-global audit
log** instead (A-H3).

**Visit model:** a *visit* is a user's time on ONE workspace; a user may hold several open visits
at once (one per tab). A visit ends on the first of:
1. explicit **Close workspace** action,
2. **logout**,
3. **session idle expiry**.

On visit end, **notifications are created** (in-app, not emailed):
- → **the visiting user's inbox** — memo: **username** (self-describing, A-M10), ws_id, visit
  start/end (and session login time + IP), script names (+ count), the last search (query / filter
  / direction), L2 views opened, layout saves.
- → **the creator's inbox**, only if the visitor ≠ creator — alert: who (username), when, what
  changed (search replaced, L2s opened, layouts adjusted).

A user visiting N workspaces in one session gets N memos.

**Notification record** — **one file per user** (`notifications/{username}.json`), list of
`{id, kind: memo|alert, title, body, read, created_at}`. Title keeps the mailbox-searchable format —
`[SQL Data Flow Visualizer] Workspace {ws_id} · {YYYY-MM-DD HH:MM}`. **All records are kept**
(user-confirmed); a write touches only the owning user's file. Timestamps use server local time.

**Pull, not push:** the user sees these on next login (unread badge + inbox panel).

### 5.5 "My workspaces" (per-user index) + reading history

- `users.json` keeps each user's **workspace index**: `workspaces: [{ws_id, role: creator |
  participant, first_opened, last_opened}]`. Membership = **created + visited** (any workspace the
  user opened lands in the index). Updated when the user creates or opens a workspace.
- On login the app shows the user's list → choose one to resume. The **workspace-id resume box**
  still opens any workspace by id (and adds it to the index on first open).
- Any opener can **read a workspace's history** via its activity log (name + IP + time + action).

### 5.6 Workspace lifecycle: quota, removal, deletion

- **Quota:** each user's index holds at most `MAX_WORKSPACES_PER_USER` entries (default **10**,
  one config constant). Adding a workspace (create, or id-open that isn't already in the index)
  when the list is full → **blocked** with "remove one from your list first" (HTTP 409 + message).
  Because a creator's remove-from-history is a **physical delete** (below), a creator can never
  hold more than 10 of their own workspaces — **the history cap IS the creation cap** (A-M2).
- **Remove from my history — ONE action, role-dependent (A-M2):**
  - **Creator** → the workspace is **physically deleted**. A **pop-up warning** precedes it;
    **first** the deletion event (`{username, ip, ts, ws_id, "workspace deleted"}`) is appended to
    the **server-global audit log**, **then** `WORKSPACE_ROOT/{ws_id}` (scripts, `meta.json`,
    `activity.json`, `views.json`) is removed and the workspace is dropped from **every** user's
    index. There is no separate "delete" path and no non-destructive remove of one's own workspace
    — for the creator, **remove IS delete**.
  - **Non-creator (participant)** → the link is removed from *that user's index only*. The server
    copy and every other user's index are untouched; the action is **recorded in the workspace's
    activity log** (`{username, ip, ts, "removed-from-own-list"}`) — the workspace and its log
    survive (A-H3).

## 6. Data model (new / extended)

| Store | Contents | Lifecycle |
|-------|----------|-----------|
| `users.json` (new) | `username → {salt, password_hash, created_at, last_login_ip, workspaces: [{ws_id, role, first_opened, last_opened}]}` | Durable; a creator's remove-from-history removes the workspace from **every** index (physical delete, A-M2); a participant's removes only their own entry |
| `notifications/{username}.json` (new) | `[notification records]`, kept forever — one file per user | Durable |
| `workspaces/{ws_id}/meta.json` (new) | `creator_username`, `created_at`, `state_version`, last-search ref, **`layouts` map** (`{"l1": …, "l2:{script}": …}`, A-M5), opened-L2 list | Durable, per workspace |
| `workspaces/{ws_id}/activity.json` (new) | NDJSON `{username, ip, ts, action, detail}`, one record per line, **O_APPEND** (A-M3) | Durable, per workspace |
| `audit.json` (new, server-global) | NDJSON `{username, ip, ts, ws_id, action}`, one record per line, **O_APPEND** (A-M3) — **deletion events** survive the workspace they describe (A-H3) | Durable, outside any workspace |
| `sessions` (in-memory) | token → `{username, ip, last_active}` | TTL 30 min / on logout |
| `open_visits` (in-memory) | `session_token → {ws_id → {opened_at, last_active}}` (session carries `username`; per-user aggregation at flush, A-M10) | Flushed on visit end (close/logout/expiry), per session |
| existing `views.json` | search views (unchanged) | Durable |

**Concurrency:** two write paths, one per store type (A-M3):
- **Audit logs — `activity.json` / `audit.json`:** written with **`O_APPEND`, one NDJSON record per
  line** — real append-only, no read-modify-write. Concurrent appends never lose a record; a
  deletion audit entry can never be dropped.
- **Shared workspace state — `meta.json`:** **CAS-gated** whole-file **write-temp + rename**
  (A-M4): the write applies only if the `state_version` it was built on still matches (single
  worker, A-M8, makes check-and-write atomic). A stale writer is told (409) and re-applies — no
  silent loss.
- **Per-user files — `users.json` / `notifications/{username}.json`:** accepted-loss whole-file
  **write-temp + rename** (last-writer-wins). Two of a user's own sessions writing at the same
  instant: the losing writer's update may be dropped — **accepted** (low simultaneous-user count).
  A race never corrupts a file; it only drops the last writer's change.

**Deployment constraint (A-M8):** the backend must run **exactly one uvicorn worker** —
`--workers 1`, pinned in the run command/Docker config. Sessions and `open_visits` are in-memory,
and the A-M4 CAS relies on single-process compare-and-rename atomicity. A multi-worker launch is a
**documented misconfiguration**: it silently breaks login (a session created on worker 1 is unknown
to worker 2), open-visit flush, and the CAS guarantee.

**Heavy-operation gate (single, global):** all CPU-heavy operations — the debugger **search** and
the analysis API (`/analyze`, `/analyze_multi`) — share **one gate** and run **one at a time**.
While one is in progress, a new one is refused with **HTTP 409 "system busy — please wait"**
instead of starting in parallel and blocking the server. (Single worker already serializes; this
turns the queue into a clear user message.)

**Migration at rollout:** pre-feature workspaces (no `creator_username`) are **removed directly**
(user-confirmed, no backup). Verify existing e2e/test fixtures are not affected before running.

## 7. API additions (draft)

- `POST /api/admin/users`  `{username, password}` — **admin-only**: create a user or reset a
  password (rejects non-`@hsbc.com` / short password); the only way a password ever changes (A-H1)
- `POST /api/auth/login`  `{username, password}` → sets session cookie; records client IP;
  **rejects unknown usernames** (not on the pre-provisioned allowlist, A-H2)
- `POST /api/auth/logout` → destroy session, flush visit memo
- `GET  /api/auth/me` → current username (+ last_login_ip)
- `GET  /api/workspaces` → **my workspaces** index (list + `{count, cap}` so the UI can show a meter)
- `POST /api/workspace` → **create** (the existing folder/zip upload, extended): server generates a
  **UUID4 `ws_id`** (A-H4), stamps `creator_username` in `meta.json`, adds to the creator's index
  (409 if over quota, A-M2/A-M6)
- `POST /api/workspace/{ws_id}/close` → end visit, write activity log, create memo (+ creator alert)
- `DELETE /api/me/workspaces/{ws_id}` → **remove from my history — role-dependent (A-M2):** as
  **creator** this physically deletes the workspace (pop-up warning; server-global audit-log entry
  written **before** removal; dropped from every index); as **non-creator** it removes only the
  caller's own index entry and records the action in the workspace's activity log. **Single
  endpoint — the separate physical-delete path was dropped** (A-M1).
- `GET  /api/workspace/{ws_id}/activity` → **read the workspace's history** (name + IP + ts + action)
- `POST /api/workspace/{ws_id}/search` (existing) → also records layout savepoints per opened L2;
  returns **409 "system busy — please wait"** if another heavy op is running
- `POST /api/analyze` / `POST /api/analyze_multi` (existing) → under the **same global heavy-op
  gate** (409 "system busy" while another heavy op runs)
- `PUT  /api/workspace/{ws_id}/layout` → autosave node positions into `meta.json.layouts` (body
  `{level: "l1"|"l2", script?, node_positions}`; frontend sends **≤1/s**; **current-state only**,
  overwrites the entry). **One endpoint** for the L1 and all L2s — the `view_id`-keyed path is
  dropped (A-M5).
- `GET  /api/workspace/{ws_id}/resume` → full current state (L1 + opened L2 + positions + state_version)
- `GET  /api/notifications` → current user's inbox; `POST /api/notifications/{id}/read`

**All endpoints are behind the login entrance** (session cookie required) — no page or API is
reachable before login; only the health endpoint stays public.

## 8. Frontend additions

- **Login entrance page — the front door before any page**: `user_name@hsbc.com` + password
  (server-validates the `@hsbc.com` format; an **unknown username is rejected** — "account not
  provisioned, contact the administrator"). **Forgot password** link → **"contact the administrator
  for a reset"** (no self-service re-register, A-H1). Every page redirects here when not logged in.
- **My workspaces dashboard** on login: the user's workspace list (role, last-opened, **quota meter
  `{count}/{cap}`**). Per row: **Open** and **Remove**. **Remove shows a warning dialog when the
  caller is the creator** ("this physically deletes the workspace for everyone") and only a
  lightweight confirm when not (link removal, your index only) (A-M2). The **workspace-id resume
  box** opens any workspace by id.
- **History panel** for a workspace: the activity log (who, when, which IP, what action).
- **"State changed by X — refreshed" toast** when the loaded workspace's `state_version` is newer
  than what the user has on screen.
- **"System busy — please wait" message** when a search is refused while another heavy analysis is
  running (409); the button re-enables when the gate frees.
- **Notification bell**: unread badge; inbox listing memos/alerts (title, ws_id, time, read/unread).
- **Close workspace** control (explicit visit-end trigger).
- **Opened-L2 strip** under the L1 navigation panel: previously-opened L2s (with saved layouts) —
  click to switch; opening an un-saved L2 recomputes fresh and becomes savable.
- **Layout autosave**: `PUT /api/workspace/{ws_id}/layout` — node x/y **at most once per second**
  while dragging, plus a **final PUT on workspace close**; silent failure handling (A-M5).

## 9. Security notes

- Usernames are enforced `*@hsbc.com`; passwords hashed (salted KDF), never plaintext, min length 6.
  Accounts are **pre-provisioned from the admin allowlist** — unknown usernames are rejected (A-H2).
- **Password recovery is admin-mediated only** — no self-service reset can overwrite an identity (A-H1).
- **Open-by-workspace-id** is the accepted loose access — any logged-in user who knows the id can
  open/edit; the creator is alerted in-app afterwards. **`ws_id` is server-generated UUID4 /
  128-bit random and no endpoint enumerates ids** (A-H4).
- **Remove-from-my-history is role-dependent (A-M2):** for the **creator** it is a physical delete —
  warning dialog, **server-global audit log written before removal** (A-H3); for a **non-creator**
  it is a personal-index operation recorded in the workspace's activity log. A creator is therefore
  bounded to at most `MAX_WORKSPACES_PER_USER` physical workspaces.
- **IP audit** makes every workspace modification attributable (name + IP + time).
- Session cookie: **`HttpOnly` + `SameSite=Lax`**, 30-min idle expiry (A-M7).
- **Same-origin check** on every state-changing request — the server verifies the `Origin`/`Referer`
  header matches the service origin; otherwise 403. The app is same-origin by design, so no CSRF
  token system is needed (A-M7).
- **Plain HTTP on the managed LAN is an accepted, documented residual risk** — no TLS on the target
  network; `SameSite=Lax` + origin check close the cookie-borne attack path (A-M7).

## 10. Decisions locked (2026-08-19, all confirmed)

1. ~~IP source~~ → **client IP** (`request.client.host`), recorded to know who is using the service;
   switch to `X-Forwarded-For` only if a trusted proxy is ever introduced.
2. ~~Old-workspace removal~~ → **remove directly**, no backup.
3. ~~Password policy~~ → **minimum length ≥ 6**.
4. ~~Session store / `open_visits` lost on restart~~ → **accepted** (A-M9) — a restart interrupts
   open visits without memo/creator alert; no persistence machinery.
5. ~~Notification retention~~ → **keep all**.
6. ~~Username format~~ → **`user_name@hsbc.com`**, enforced.
7. ~~Account provisioning~~ → **pre-provisioned allowlist** — unknown usernames rejected at login (A-H2).
8. ~~Workspace delete~~ → **one role-dependent remove-from-my-history (A-M2)**: creator = physical
   delete (warning + audit-before-removal, dropped from every index); non-creator = link removal
   only, logged in the workspace's activity log.
9. ~~Quota~~ → **`MAX_WORKSPACES_PER_USER` default 10** (config constant); opening a new one at the
   cap requires removing one from the list first. The history cap **is** the creation cap — a
   creator can never hold more than 10 of their own workspaces (A-M2).
10. ~~Password recovery~~ → **admin-mediated reset only** — no self-service path overwrites an
    existing identity (A-H1).
11. ~~Concurrent editing~~ → **CAS-conditional saves on `state_version`** (A-M4): a stale save gets
    409 → auto reload + re-apply + "state changed by X — refreshed" notice. No locking; debounced
    saves (≤1/s, final on close) keep conflict windows rare.
12. ~~"My workspaces" membership~~ → **created + visited**.
13. ~~L1 layout~~ → **saved too** — positions autosaved for the current L1 *and* each opened L2.
14. ~~Multiple tabs~~ → **per-(user, workspace) open-visits registry**; all open visits flush on
    logout/expiry (one memo each).
15. ~~Login gate~~ → **login entrance page before any page**; only the health endpoint stays public.
16. ~~Concurrent write loss~~ → **accepted** (low simultaneous users, **single uvicorn worker —
    enforced, A-M8**); files still written atomically (temp + rename) so a race never corrupts a
    file.
17. ~~Notifications storage~~ → **one file per user** `notifications/{username}.json`.
18. ~~Layout write cadence~~ → **≤1/s from the frontend + final write on workspace close**; layout
    file keeps **current state only** (never grows). The debounce also **minimizes CAS conflict
    windows** (A-M4): accumulated operations coalesce into one save per second.
19. ~~Heavy CPU load~~ → **one global heavy-op gate** (debugger search + `/analyze` + `/analyze_multi`)
    — while one runs, a new one is refused with "system busy — please wait" (HTTP 409).
20. ~~Deletion audit (A-H3)~~ → creator physical delete appends to the **server-global audit log
    before removal**; non-creator remove-from-list is logged in the workspace's activity log.
21. ~~Workspace id (A-H4)~~ → `ws_id` is **server-generated UUID4 / 128-bit random**; **no endpoint
    lists workspace ids**.
22. ~~DELETE paths (A-M1)~~ → **one endpoint** `DELETE /api/me/workspaces/{ws_id}`, role-dependent
    (A-M2); the separate physical-delete endpoint was **dropped** — nothing to confuse (A-M1).
23. ~~Quota vs server space (A-M2)~~ → **the history cap is the creation cap**: a creator's
    remove-from-history physically deletes, so a creator can never hold > `MAX_WORKSPACES_PER_USER`
    of their own workspaces.
24. ~~Audit-log append (A-M3)~~ → **`O_APPEND`, one NDJSON record per line** for `activity.json`
    and `audit.json` — real append-only, no read-modify-write, concurrent appends never lost.
    State files (`users.json`/`notifications`/`meta.json`) keep temp+rename (accepted-loss).
25. ~~`state_version` monotonicity (A-M4)~~ → **CAS-conditional state writes**: a save applies only
    if the `state_version` it was built on still matches; else **409 → auto reload + re-apply** +
    "state changed by X" notice. Saves are **debounced (≤1/s, final on close)** so accumulated
    operations coalesce and conflict windows stay rare (user-confirmed 2026-08-21).
26. ~~Layout storage (A-M5)~~ → **one place: `meta.json` `layouts` map** (`l1` + `l2:{script}`),
    written via a **single endpoint** `PUT /api/workspace/{ws_id}/layout`; `views.json` stays
    search-view records only.
27. ~~Workspace-create endpoint (A-M6)~~ → **`POST /api/workspace`** = the existing folder/zip
    upload, extended: server-generated **UUID4 `ws_id`** (A-H4), `creator_username` stamped,
    quota checked (A-M2).
28. ~~CSRF / cookie attributes (A-M7)~~ → session cookie **`HttpOnly` + `SameSite=Lax`** + a
    **same-origin check** (`Origin`/`Referer`) on every state-changing request; no CSRF token for
    a same-origin app; plain HTTP on the LAN documented as an accepted residual risk.
29. ~~Single-worker constraint (A-M8)~~ → backend runs **exactly one uvicorn worker**
    (`--workers 1`, pinned); sessions/`open_visits` stay in-memory and the A-M4 CAS stays
    single-process atomic. A multi-worker launch is a documented misconfiguration.
30. ~~Restart vs open-visit flush (A-M9)~~ → **accepted explicitly**: `open_visits` is in-memory;
    a restart drops active visits silently (no memo/creator alert for the interrupted stretch). On
    next login the user continues. No persist/flush-at-startup machinery.
31. ~~open_visits keyed by username (A-M10)~~ → keyed by **session token**; the session carries
    `username`. Flush is **per-session**; memo/creator-alert is **aggregated per user** (created
    only when the last of a user's sessions closes the workspace). **Memos carry the username**
    (confirmed 2026-08-21).
