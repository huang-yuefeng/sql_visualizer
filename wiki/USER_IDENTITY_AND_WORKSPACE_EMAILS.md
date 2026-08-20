# User Identity & Workspace Collaboration — Local Accounts (no email)

## Status

> **Design settled 2026-08-19 — implementation awaiting the go-command; NOT implemented in any
> release (no code exists).** Traceability rows **R31.1–R31.13** live in
> `wiki/REQUIREMENTS_TRACEABILITY.md`. `wiki/CODE_REVIEW_2026-08-19.md` (Part A, read-only) flags
> High-severity design flaws that must be resolved before implementation: **A-H1** unauthenticated
> account takeover via re-register; **A-H2** self-asserted identity; **A-H3** workspace deletion
> destroys its own audit trail; **A-H4** enumerable workspace ids. Plus Medium findings **A-M1–A-M10**.

> Design note — revised 2026-08-19 (6th revision). Email is **dropped** (no usable
> mail path on the target network). Replaced with **local accounts (`@hsbc.com` usernames) + IP
> audit + in-app notifications + per-workspace activity log + a per-user "my workspaces" index**.
> **All decisions locked — design settled, awaiting the go-command to implement. No code changed.**

**Change vs the 2026-08-14 email design:** every email function maps to an in-app equivalent —
OTP login → local accounts; memo/creator-alert emails → notification inboxes; mailbox-searchable
titles → notification-card titles. **Added later revisions:** `@hsbc.com`-enforced usernames,
per-operation **username + IP** recording, a per-user workspace index on login, and a
**creator-only physical delete + quota + remove-from-own-history** workspace lifecycle.

## 1. Purpose

Make the SQL Data Flow Visualizer a multi-user service where:

1. **A login entrance page gates every page of the service** — no page is reachable before login.
   Users log in with their HSBC-postfix email **`user_name@hsbc.com`** (format enforced, validated
   as `*@hsbc.com`) plus a **password** created on first login. The email string is an identifier
   only — **no mail is ever sent**.
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
    workspace index. Created the **first time** the user logs in (self-registration).
  - **Workspace** = own id + **shared current state** + readable **history** (activity log).
- **Account ↔ workspace is 1:N.** A user may create or visit many workspaces.
- **"My workspaces" (per-user index, personal):** the list of workspaces the user has **created or
  visited** (role: creator/participant, last-opened time). Shown on login so the user can choose one.
- **Workspace current state (shared, not personal):** one L1 (the last search) + the opened L2s
  with saved layouts. Anyone who opens the workspace by id sees **this same current state**;
  last-writer-wins. This is **not** a per-user search-history list.
- **Workspace history (readable by any opener):** the per-workspace **activity log** — who (name +
  IP) did what, when. This is what "he can read the history of this workspace" means.

The earlier ambiguity is settled: "personal" applies to the **workspace index under an account**;
the workspace's **search state** stays shared and current-state-only.

## 3. Sharing model (how users share a workspace)

- Users share by exchanging the **workspace id** — or simply a link
  `http://192.168.0.66:8000/…?ws={ws_id}`. Any **logged-in** user who knows the id can open and
  edit it. No email, no external channel required.
- The workspace records its **creator** (username) at creation. When someone else works on it, the
  creator is **alerted in-app** (next login).
- Every operation writes to the workspace's **activity log** with the actor's **username + IP** —
  the shared audit trail.

## 4. Agreed decisions (Q&A summary)

| # | Question | Decision |
|---|----------|----------|
| — | Login | **Username MUST be `*@hsbc.com`** (format-validated) + **password**; first-time username **self-registers**. Client **IP recorded at login** and on every workspace operation. No email, no OTP. |
| — | Logout | **Idle timeout (30 min)**; also a logout button. Visit flush triggers: workspace close / session expiry / logout. |
| — | One L1 + multiple L2 | Keep. One search = one L1; the L2s the user opened are retained. |
| Q2 | Last-search state | **Shared**, workspace-wide. Resume = current workspace state, never personal history. Last-writer (closes last) wins. |
| Q3 | Access model | **Open by workspace id** — any logged-in user who knows the id can open and edit; creator is only alerted (in-app). (Known simple, slight risk, accepted for now.) |
| Q4 | Layout save | **L1 and L2 node x/y are both autosaved** on each drag-end. Only the L2 views the user actually **opened** are retained. Save **node x/y only**; zoom/pan ignored. |
| — | Multiple tabs | A user may have several workspaces open in different tabs. Visits are tracked **per (user, workspace)**, not per session; logout/expiry flushes **all** open visits (one memo each). |
| — | Login gate | **Login entrance page before any page** — the whole service is behind it; only the health endpoint stays public. |
| Q5 | Concurrent users | **Last-write-wins** + a lightweight **version-stamp notice** ("state changed by X — refreshed"). No locking. |
| Q6 | Accounts | **Persisted local accounts** (self-registered `@hsbc.com` + password). Stable identity is what makes the inbox, the per-user index, and "creator" meaningful. |
| Q7 | Notifications | **In-app, keep all records, one file per user** (`notifications/{username}.json`). One memo per workspace-close. **No script contents** — script names, search table/field names, ws_id, time. Enough to understand what happened. |
| Q8 | Idle timeout | **30 minutes**. Memo added on workspace close / session expiry / logout. |
| — | Concurrent writes | **Accepted**: losing the rarer concurrent update is OK (low simultaneous-user count). Files are still written atomically (temp + rename) so a race **never corrupts a file** — it only drops the losing writer's update. |
| — | Layout write cadence | Frontend writes layout **at most once per second**; a **final write on workspace close**. The layout file keeps **only current state** (per-view `{node_id:[x,y]}`), never history — its size does not grow. |
| — | Heavy CPU load | **One global heavy-op gate** covering the debugger **search** and the analysis API (`/analyze`, `/analyze_multi`). While any one is running, a new one is **refused with "system busy — please wait"** instead of starting in parallel and blocking the server. |
| — | IP audit | **Every workspace operation recorded as {username, ip, ts, action, detail}** — "who modified this" is always answerable. |
| — | Workspace delete | **Creator-only physical delete** (removes the workspace from the server and from everyone's index). **Everyone** can **remove a workspace from their own history** (their index only — never the server copy). |
| — | Quota | Each user may **keep at most `MAX_WORKSPACES_PER_USER`** workspaces in their "my workspaces" list (default **10**, single config constant). At the cap, opening a new workspace (create or id-open) requires removing one from the list first. |
| — | Password recovery | **Re-register** — a "forgot password" path recreates the username with a new password, replacing the old account record (inbox + workspace index reset; workspaces themselves unaffected). |
| — | Old workspaces | **Removed** at rollout — pre-feature workspaces (no creator) are deleted; all workspaces from this point carry a creator. |

## 5. Model

### 5.1 Identity & login (local accounts)

- Login page: **username (must match `*@hsbc.com`) + password**. An unknown username is **created
  on first login** (self-registration) — the account's `created_at` records first login.
- Format validation on the server: the username must match `*@hsbc.com`. It is **never** used as a
  mailbox — no mail is sent anywhere.
- Passwords hashed with a salted KDF (PBKDF2-HMAC via stdlib `hashlib`; no new dependencies).
  Never stored or logged in plaintext. Minimum length **≥ 6**.
- **Password recovery = re-register.** A "forgot password" path on the login page recreates the
  username with a new password and replaces the previous account record (inbox + workspace index
  reset). Workspaces are independent and unaffected; `creator_username` stays as originally
  recorded. Low risk accepted: workspaces are already open-by-id to any logged-in user.
- The client **IP** is captured at login (`request.client.host`), stored on the session and on the
  user record (`last_login_ip`), and included in the visit's audit entries.
- Successful login creates a **session**; identity is an `HttpOnly` cookie.

### 5.2 Sessions & open visits

- Server-side sessions keyed by an opaque token in an `HttpOnly` cookie (not readable by JS),
  holding `{username, ip, last_active}`.
- **Open-visits registry (per user, per workspace):** `username → {ws_id → {opened_at,
  last_active}}`. A user may have several workspaces open at once (multiple tabs); each is an
  independent visit.
- **Idle timeout 30 min** — activity extends it; on expiry the session is destroyed and **all**
  open visits flush (one memo per workspace + creator alerts where applicable). A long-running
  search that completes extends the session (it counts as activity).
- Explicit **logout** button ends the session immediately (same flush of all open visits).
- Session store is in-memory (lost on container restart — **accepted**, noted in §10).

### 5.3 Workspace state (shared, durable)

- A workspace = `WORKSPACE_ROOT/{ws_id}/` (existing) plus **`meta.json`**:
  - `creator_username` (fixed at creation)
  - `created_at`
  - a monotonically increasing **`state_version`** (bumped on every state write — drives the
    concurrent-editing notice)
  - the **last search state**: exactly one L1 (the search) + the list of **opened L2 views** —
    **both the L1 and each opened L2 carry persisted node x/y layouts**
- **Last search is shared and current-state-only.** A new search by anyone replaces the stored one.
  Resume by ws_id shows the current state, not history. Last-writer-wins on every write (no locking).
- **Concurrent-editing notice:** when the frontend loads/receives state whose `state_version` is
  newer than what it last loaded, it shows "state changed by X at HH:MM — refreshed" and re-renders.
- **Layout persistence (L1 + L2):** the frontend reports node x/y **at most once per second** while
  dragging, plus a **final write on workspace close**, for the **current L1 and for each opened
  L2**; backend stores per-view `{node_id: [x,y]}` as **current state only** (replaced on each
  save, never appended — file size does not grow). On resume, positions are re-applied instead of
  recomputed; **positions for node ids that no longer exist are skipped, not errors**. Zoom/pan
  intentionally not saved. (History of layout *actions* lives in the activity log, not the layout file.)
- The existing `views.json` (search views) stays; `meta.json` adds creator + layout positions +
  opened-L2 registry.

### 5.4 Activity log + in-app notifications

**Activity log (per workspace, append-only)** — `workspaces/{ws_id}/activity.json`. Every entry is
`{username, ip, ts, action, detail}`. Events include: visit start, search performed, L2 opened,
layout saved, visit end, workspace deleted. This is the durable, IP-audited "who modified this"
record, readable by any opener.

**Visit model:** a *visit* is a user's time on ONE workspace; a user may hold several open visits
at once (one per tab). A visit ends on the first of:
1. explicit **Close workspace** action,
2. **logout**,
3. **session idle expiry**.

On visit end, **notifications are created** (in-app, not emailed):
- → **the visiting user's inbox** — memo: ws_id, visit start/end (and session login time + IP),
  script names (+ count), the last search (query / filter / direction), L2 views opened, layout saves.
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
- **Remove from my list** (any user): deletes the entry from *that user's index only*. Never
  touches the server copy or any other user's index. Frees only an index slot — **never server
  space**.
- **Delete workspace** (creator only): physically removes `WORKSPACE_ROOT/{ws_id}` (scripts,
  `meta.json`, `activity.json`, `views.json`) from the server and removes it from **every** user's
  index. Non-creators have no physical-delete path. A creator who needs server space back uses
  Delete, not Remove-from-list.

## 6. Data model (new / extended)

| Store | Contents | Lifecycle |
|-------|----------|-----------|
| `users.json` (new) | `username → {salt, password_hash, created_at, last_login_ip, workspaces: [{ws_id, role, first_opened, last_opened}]}` | Durable; index entries removed on Remove-from-list or on workspace delete |
| `notifications/{username}.json` (new) | `[notification records]`, kept forever — one file per user | Durable |
| `workspaces/{ws_id}/meta.json` (new) | `creator_username`, `created_at`, `state_version`, last-search ref, opened-L2 list with `{script, node_positions}` | Durable, per workspace |
| `workspaces/{ws_id}/activity.json` (new) | append-only `{username, ip, ts, action, detail}` | Durable, per workspace |
| `sessions` (in-memory) | token → `{username, ip, last_active}` | TTL 30 min / on logout |
| `open_visits` (in-memory) | `username → {ws_id → {opened_at, last_active}}` | Flushed on visit end (close/logout/expiry) |
| existing `views.json` | search views (unchanged) | Durable |

**Concurrency (accepted-loss):** `users.json` / `notifications/{username}.json` / `meta.json` /
`activity.json` can be written by two users at the same instant. The losing writer's update may be
dropped — **accepted** (low simultaneous-user count, single uvicorn worker). Every write is still
atomic (**write-temp + rename**) so a race never corrupts a file; it only drops the last writer's
change. `activity.json` is append-only (no read-modify-write).

**Heavy-operation gate (single, global):** all CPU-heavy operations — the debugger **search** and
the analysis API (`/analyze`, `/analyze_multi`) — share **one gate** and run **one at a time**.
While one is in progress, a new one is refused with **HTTP 409 "system busy — please wait"**
instead of starting in parallel and blocking the server. (Single worker already serializes; this
turns the queue into a clear user message.)

**Migration at rollout:** pre-feature workspaces (no `creator_username`) are **removed directly**
(user-confirmed, no backup). Verify existing e2e/test fixtures are not affected before running.

## 7. API additions (draft)

- `POST /api/auth/register`  `{username, password}` — rejects non-`@hsbc.com` / short password
- `POST /api/auth/login`  `{username, password}` → sets session cookie; records client IP
- `POST /api/auth/logout` → destroy session, flush visit memo
- `GET  /api/auth/me` → current username (+ last_login_ip)
- `GET  /api/workspaces` → **my workspaces** index (list + `{count, cap}` so the UI can show a meter)
- `POST /api/workspace/{ws_id}/close` → end visit, write activity log, create memo (+ creator alert)
- `DELETE /api/workspace/{ws_id}` → **creator-only physical delete** (removes from all indexes)
- `DELETE /api/workspaces/{ws_id}` → **remove from own history only** (index), no server change
- `GET  /api/workspace/{ws_id}/activity` → **read the workspace's history** (name + IP + ts + action)
- `POST /api/workspace/{ws_id}/search` (existing) → also records layout savepoints per opened L2;
  returns **409 "system busy — please wait"** if another heavy op is running
- `POST /api/analyze` / `POST /api/analyze_multi` (existing) → under the **same global heavy-op
  gate** (409 "system busy" while another heavy op runs)
- `PUT  /api/workspace/{ws_id}/views/{view_id}/layout` → autosave node positions (frontend sends
  **≤1/s**; **current-state only**, overwrites the view's positions)
- `GET  /api/workspace/{ws_id}/resume` → full current state (L1 + opened L2 + positions + state_version)
- `GET  /api/notifications` → current user's inbox; `POST /api/notifications/{id}/read`
- Workspace **create** records `creator_username` in `meta.json` and adds to the creator's index
  (409 if over quota).

**All endpoints are behind the login entrance** (session cookie required) — no page or API is
reachable before login; only the health endpoint stays public.

## 8. Frontend additions

- **Login entrance page — the front door before any page**: `user_name@hsbc.com` + password
  (server-validates the `@hsbc.com` format; unknown usernames self-register). **Forgot password**
  link → re-register flow (explicit confirm that the old inbox/index will be replaced). Every page
  redirects here when not logged in.
- **My workspaces dashboard** on login: the user's workspace list (role, last-opened, **quota meter
  `{count}/{cap}`**). Per row: **Open**, **Remove from my list** (everyone), **Delete workspace**
  (creator-only, confirmation dialog). The **workspace-id resume box** opens any workspace by id.
- **History panel** for a workspace: the activity log (who, when, which IP, what action).
- **"State changed by X — refreshed" toast** when the loaded workspace's `state_version` is newer
  than what the user has on screen.
- **"System busy — please wait" message** when a search is refused while another heavy analysis is
  running (409); the button re-enables when the gate frees.
- **Notification bell**: unread badge; inbox listing memos/alerts (title, ws_id, time, read/unread).
- **Close workspace** control (explicit visit-end trigger).
- **Opened-L2 strip** under the L1 navigation panel: previously-opened L2s (with saved layouts) —
  click to switch; opening an un-saved L2 recomputes fresh and becomes savable.
- **Layout autosave**: PUT node x/y **at most once per second** while dragging, plus a **final PUT
  on workspace close**; silent failure handling.

## 9. Security notes

- Usernames are enforced `*@hsbc.com`; passwords hashed (salted KDF), never plaintext, min length 6.
- **Open-by-workspace-id** is the accepted loose access — any logged-in user who knows the id can
  open/edit; the creator is alerted in-app afterwards.
- **Physical delete is creator-only**; Remove-from-list is strictly a personal-index operation.
- **IP audit** makes every workspace modification attributable (name + IP + time).
- HttpOnly session cookie; 30-min idle expiry.

## 10. Decisions locked (2026-08-19, all confirmed)

1. ~~IP source~~ → **client IP** (`request.client.host`), recorded to know who is using the service;
   switch to `X-Forwarded-For` only if a trusted proxy is ever introduced.
2. ~~Old-workspace removal~~ → **remove directly**, no backup.
3. ~~Password policy~~ → **minimum length ≥ 6**.
4. ~~Session store lost on restart~~ → **accepted**.
5. ~~Notification retention~~ → **keep all**.
6. ~~Username format~~ → **`user_name@hsbc.com`**, enforced.
7. ~~Account provisioning~~ → **self-registration** on first login.
8. ~~Workspace delete~~ → **creator-only physical delete**; everyone can **remove from own history**.
9. ~~Quota~~ → **`MAX_WORKSPACES_PER_USER` default 10** (config constant); opening a new one at the
   cap requires removing one from the list first.
10. ~~Password recovery~~ → **re-register** (replaces the old account's inbox + index; workspaces
    unaffected).
11. ~~Concurrent editing~~ → **last-write-wins + version-stamp notice** ("state changed by X — refreshed").
12. ~~"My workspaces" membership~~ → **created + visited**.
13. ~~L1 layout~~ → **saved too** — positions autosaved for the current L1 *and* each opened L2.
14. ~~Multiple tabs~~ → **per-(user, workspace) open-visits registry**; all open visits flush on
    logout/expiry (one memo each).
15. ~~Login gate~~ → **login entrance page before any page**; only the health endpoint stays public.
16. ~~Concurrent write loss~~ → **accepted** (low simultaneous users, single worker); files still
    written atomically (temp + rename) so a race never corrupts a file.
17. ~~Notifications storage~~ → **one file per user** `notifications/{username}.json`.
18. ~~Layout write cadence~~ → **≤1/s from the frontend + final write on workspace close**; layout
    file keeps **current state only** (never grows).
19. ~~Heavy CPU load~~ → **one global heavy-op gate** (debugger search + `/analyze` + `/analyze_multi`)
    — while one runs, a new one is refused with "system busy — please wait" (HTTP 409).
