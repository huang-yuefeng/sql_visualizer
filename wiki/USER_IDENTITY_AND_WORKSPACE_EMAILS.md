# User Identity & Workspace Collaboration — Local Accounts (no email)

> Design note — revised 2026-08-19 (3rd revision). Email is **dropped** (no usable
> mail path on the target network). Replaced with **local accounts (`@hsbc.com` usernames) + IP
> audit + in-app notifications + per-workspace activity log + a per-user "my workspaces" index**.
> **All decisions locked — design settled, awaiting the go-command to implement. No code changed.**

**Change vs the 2026-08-14 email design:** every email function maps to an in-app equivalent —
OTP login → local accounts; memo/creator-alert emails → notification inboxes; mailbox-searchable
titles → notification-card titles. **Added (2nd revision):** `@hsbc.com`-enforced usernames,
per-operation **username + IP** recording, and a per-user workspace index shown on login.

## 1. Purpose

Make the SQL Data Flow Visualizer a multi-user service where:

1. Users log in with their HSBC-postfix email **`user_name@hsbc.com`** (format enforced, validated
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
- **"My workspaces" (per-user index, personal):** the list of workspaces the user has created or
  worked on (role: creator/participant, last-opened time). Shown on login so the user can choose one.
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
| Q4 | Multiple L2 + layout save | Only the L2 views the user actually **opened** are retained. **Autosave on each drag-end.** Save **node x/y only**; zoom/pan ignored. |
| Q5 | Concurrent users | **Last-write-wins**, no locking/version stamps. |
| Q6 | Accounts | **Persisted local accounts** (self-registered `@hsbc.com` + password). Stable identity is what makes the inbox, the per-user index, and "creator" meaningful. |
| Q7 | Notifications | **In-app, keep all records.** One memo per workspace-close. **No script contents** — script names, search table/field names, ws_id, time. Enough to understand what happened. |
| Q8 | Idle timeout | **30 minutes**. Memo added on workspace close / session expiry / logout. |
| — | IP audit | **Every workspace operation recorded as {username, ip, ts, action, detail}** — "who modified this" is always answerable. |
| — | Old workspaces | **Removed** at rollout — pre-feature workspaces (no creator) are deleted; all workspaces from this point carry a creator. |

## 5. Model

### 5.1 Identity & login (local accounts)

- Login page: **username (must match `*@hsbc.com`) + password**. An unknown username is **created
  on first login** (self-registration) — the account's `created_at` records first login.
- Format validation on the server: the username must match `*@hsbc.com`. It is **never** used as a
  mailbox — no mail is sent anywhere.
- Passwords hashed with a salted KDF (PBKDF2-HMAC via stdlib `hashlib`; no new dependencies).
  Never stored or logged in plaintext.
- The client **IP** is captured at login (`request.client.host`), stored on the session and on the
  user record (`last_login_ip`), and included in the visit's audit entries.
- Successful login creates a **session**; identity is an `HttpOnly` cookie.

### 5.2 Sessions

- Server-side sessions keyed by an opaque token in an `HttpOnly` cookie (not readable by JS),
  holding `{username, ip, ws_id open, opened_at, last_active}`.
- **Idle timeout 30 min** — activity extends it; on expiry the session is destroyed and the open
  workspace's visit is flushed (memo + maybe alert).
- Explicit **logout** button ends the session immediately (same flush).
- Session store is in-memory (lost on container restart — **accepted**, noted in §9).

### 5.3 Workspace state (shared, durable)

- A workspace = `WORKSPACE_ROOT/{ws_id}/` (existing) plus **`meta.json`**:
  - `creator_username` (fixed at creation)
  - `created_at`
  - the **last search state**: exactly one L1 (the search) + the list of **opened L2 views**, each
    with its **persisted node x/y layout**
- **Last search is shared and current-state-only.** A new search by anyone replaces the stored one.
  Resume by ws_id shows the current state, not history. Last-writer-wins on every write (no locking).
- **Layout persistence:** the frontend reports node x/y on each drag-end (debounced autosave);
  backend stores per-view `{node_id: [x,y]}`. On resume, positions are re-applied instead of
  recomputed. Zoom/pan intentionally not saved.
- The existing `views.json` (search views) stays; `meta.json` adds creator + layout positions +
  opened-L2 registry.

### 5.4 Activity log + in-app notifications

**Activity log (per workspace, append-only)** — `workspaces/{ws_id}/activity.json`. Every entry is
`{username, ip, ts, action, detail}`. Events include: visit start, search performed, L2 opened,
layout saved, visit end. This is the durable, IP-audited "who modified this" record, readable by
any opener.

**Visit model:** a *visit* is a user's time on ONE workspace. It ends on the first of:
1. explicit **Close workspace** action,
2. **logout**,
3. **session idle expiry**.

On visit end, **notifications are created** (in-app, not emailed):
- → **the visiting user's inbox** — memo: ws_id, visit start/end (and session login time + IP),
  script names (+ count), the last search (query / filter / direction), L2 views opened, layout saves.
- → **the creator's inbox**, only if the visitor ≠ creator — alert: who (username), when, what
  changed (search replaced, L2s opened, layouts adjusted).

A user visiting N workspaces in one session gets N memos.

**Notification record** (`notifications.json`, per username): `{id, kind: memo|alert, title, body,
read, created_at}`. Title keeps the mailbox-searchable format —
`[SQL Data Flow Visualizer] Workspace {ws_id} · {YYYY-MM-DD HH:MM}`. **All records are kept**
(user-confirmed).

**Pull, not push:** the user sees these on next login (unread badge + inbox panel).

### 5.5 "My workspaces" (per-user index) + reading history

- `users.json` keeps each user's **workspace index**: `workspaces: [{ws_id, role: creator |
  participant, first_opened, last_opened}]`. Updated when the user creates or opens a workspace.
- On login the app shows the user's list → choose one to resume. The **workspace-id resume box**
  still opens any workspace by id (and adds it to the index on first open).
- Any opener can **read a workspace's history** via its activity log (name + IP + time + action).

## 6. Data model (new / extended)

| Store | Contents | Lifecycle |
|-------|----------|-----------|
| `users.json` (new) | `username → {salt, password_hash, created_at, last_login_ip, workspaces: [{ws_id, role, first_opened, last_opened}]}` | Durable |
| `notifications.json` (new) | `username → [notification records]` (kept forever) | Durable |
| `workspaces/{ws_id}/meta.json` (new) | `creator_username`, `created_at`, last-search ref, opened-L2 list with `{script, node_positions}` | Durable, per workspace |
| `workspaces/{ws_id}/activity.json` (new) | append-only `{username, ip, ts, action, detail}` | Durable, per workspace |
| `sessions` (in-memory) | token → `{username, ip, ws_id open, opened_at, last_active}` | TTL 30 min / on logout |
| existing `views.json` | search views (unchanged) | Durable |

**Migration at rollout:** pre-feature workspaces (no `creator_username`) are **removed**
(user-confirmed). Optionally keep a one-time backup copy (§9).

## 7. API additions (draft)

- `POST /api/auth/register`  `{username, password}` — rejects non-`@hsbc.com`; first-time only
- `POST /api/auth/login`  `{username, password}` → sets session cookie; records client IP
- `POST /api/auth/logout` → destroy session, flush visit memo
- `GET  /api/auth/me` → current username (+ last_login_ip)
- `GET  /api/workspaces` → **my workspaces** index (dashboard list)
- `POST /api/workspace/{ws_id}/close` → end visit, write activity log, create memo (+ creator alert)
- `GET  /api/workspace/{ws_id}/activity` → **read the workspace's history** (name + IP + ts + action)
- `POST /api/workspace/{ws_id}/search` (existing) → also records layout savepoints per opened L2
- `PUT  /api/workspace/{ws_id}/views/{view_id}/layout` → autosave node positions
- `GET  /api/workspace/{ws_id}/resume` → full current state (L1 + opened L2 + positions)
- `GET  /api/notifications` → current user's inbox; `POST /api/notifications/{id}/read`
- Workspace **create** records `creator_username` in `meta.json` and adds to the creator's index.

Existing endpoints become auth-gated (session cookie required).

## 8. Frontend additions

- **Login page**: `user_name@hsbc.com` + password (server-validates the `@hsbc.com` format;
  unknown usernames self-register).
- **My workspaces dashboard** on login: the user's workspace list (role, last-opened) — click to
  resume. The **workspace-id resume box** in the top bar opens any workspace by id.
- **History panel** for a workspace: the activity log (who, when, which IP, what action) — the
  "who modified this" view.
- **Notification bell**: unread badge; inbox listing memos/alerts (title, ws_id, time, read/unread).
- **Close workspace** control (explicit visit-end trigger).
- **Opened-L2 strip** under the L1 navigation panel: previously-opened L2s (with saved layouts) —
  click to switch; opening an un-saved L2 recomputes fresh and becomes savable.
- **Layout autosave**: on drag-end, debounced (~1 s) PUT of node x/y; silent failure handling.

## 9. Security notes

- Usernames are enforced `*@hsbc.com`; passwords hashed (salted KDF), never plaintext.
- **Open-by-workspace-id** is the accepted loose access — any logged-in user who knows the id can
  open/edit; the creator is alerted in-app afterwards. (Matches the earlier "simple but a little
  dangerous, use it initially" decision.)
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
