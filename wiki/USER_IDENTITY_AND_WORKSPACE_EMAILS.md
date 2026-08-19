# User Identity & Workspace Collaboration — Local Accounts (no email)

> Design note — revised 2026-08-19. **Email is dropped** (no usable mail path on the target
> network). Replaced with **local username/password accounts + in-app notifications + a
> per-workspace activity log**. No code changed.

**Change vs the 2026-08-14 email design:** every email function maps to an in-app equivalent —
OTP login → local accounts; memo/creator-alert emails → notification inboxes; mailbox-searchable
titles → notification-card titles. The workspace/resume/layout core is unchanged.

## 1. Purpose

Make the SQL Data Flow Visualizer a multi-user service where:

1. Users identify themselves by a **local username** (chosen once, any string — may still look
   like `user_name@hsbc.com` if users prefer, but it is just an identifier, never a mailbox).
2. Work is organized by **workspace id** — the shared unit of state.
3. When a user finishes a workspace, an **in-app memo** of what happened is added to that user's
   notification inbox; if the user is not the workspace's **creator**, the creator's inbox gets an
   **alert**. (In-app replaces email — it is **pull**: the user sees it on next login, not pushed.)
4. A user can resume a previous workspace by entering its id, restoring the full current state
   **including manually-adjusted L1/L2 layouts** — the layout work is the user's main contribution
   and must survive.

Environment: the target machine is on a strictly managed network — **no internet, and no usable
mail path** (verified 2026-08-14: no mailer binaries, no mail configs, no SMTP ports). Everything
lives inside the deployed web app.

## 2. Sharing model (how users share a workspace)

- Users share by exchanging the **workspace id** — or simply a link
  `http://192.168.0.66:8000/…?ws={ws_id}`. Any **logged-in** user who knows the id can open and
  edit it. No email, no external channel required.
- The workspace records its **creator_username** at creation. When someone else works on it, the
  creator is **alerted in-app** (next time they log in).
- The workspace's **activity log** (section 3.4) is the shared audit trail — everyone who opens the
  workspace can see who did what and when.

## 3. Agreed decisions (Q&A summary)

| # | Question | Decision |
|---|----------|----------|
| — | Login | **Local username + password** (hashed, per-user salt). First-time username **self-registers**. No email, no OTP. |
| — | Logout | **Idle timeout (30 min)**; also a logout button. Visit flush triggers: workspace close / session expiry / logout. |
| — | One L1 + multiple L2 | Keep. One search = one L1; the L2s the user opened are retained. |
| Q2 | Last-search state | **Shared**, workspace-wide. Resume = current workspace state, never personal history. Last-writer (closes last) wins. |
| Q3 | Access model | **Open by workspace id** — any logged-in user who knows the id can open and edit; creator is only alerted (in-app). (Known simple, slight risk, accepted for now.) |
| Q4 | Multiple L2 + layout save | Only the L2 views the user actually **opened** are retained. **Autosave on each drag-end.** Save **node x/y only**; zoom/pan ignored. |
| Q5 | Concurrent users | **Last-write-wins**, no locking/version stamps. |
| Q6 | Accounts | **Persisted local accounts** (flipped from the ephemeral-OTP decision: a stable account is what makes the in-app inbox and "creator" meaningful now that email cannot re-identify a user). |
| Q7 | Memo content | One memo per workspace-close. **No script contents** — script names, search table/field names, ws_id, time. Enough to understand what happened. |
| Q8 | Idle timeout | **30 minutes**. Memo added on workspace close / session expiry / logout. |

## 4. Model

### 4.1 Identity & login (local accounts)

- Login page: **username + password**. If the username is unknown, it is **created on first
  login** (self-registration) — the natural local-account analogue of the old "auto-create any
  email" rule.
- Passwords hashed with a salted KDF (PBKDF2-HMAC via stdlib `hashlib`; no new dependencies).
  Never stored or logged in plaintext.
- Successful login creates a **session**; identity is an `HttpOnly` cookie.
- Username convention: free-form, but users may adopt `user_name@hsbc.com`-style ids for
  continuity — treated purely as a string.

### 4.2 Sessions

- Server-side sessions keyed by an opaque token in an `HttpOnly` cookie (not readable by JS).
- **Idle timeout 30 min** — activity extends it; on expiry the session is destroyed and the open
  workspace's visit is flushed (memo + maybe alert).
- Explicit **logout** button ends the session immediately (same flush).
- Session store is in-memory (lost on container restart — acceptable edge case; noted in §8).

### 4.3 Workspace state (shared, durable) — unchanged core

- A workspace = `WORKSPACE_ROOT/{ws_id}/` (existing) plus a **workspace metadata record**
  (`meta.json`):
  - `creator_username` (fixed at creation)
  - `created_at`
  - the **last search state**: exactly one L1 (the search) + the list of **opened L2 views**,
    each with its **persisted node x/y layout**
- **Last search is shared and current-state-only.** A new search by anyone replaces the stored one.
  Resume by ws_id shows the current state, not history. Last-writer-wins on every write (no locking).
- **Layout persistence:** the frontend reports node x/y on each drag-end (debounced autosave);
  backend stores per-view `{node_id: [x,y]}`. On resume, positions are re-applied instead of
  recomputed. Zoom/pan intentionally not saved.
- The existing `views.json` (search views) stays; `meta.json` adds creator + layout positions +
  opened-L2 registry.

### 4.4 Activity log + in-app notifications (replaces email)

**Activity log (per workspace, append-only)** — `workspaces/{ws_id}/activity.json`:
every meaningful event, tagged `{username, ts}`: visit start, search performed, L2 opened, layout
saved, visit end. This is the durable "what happened" record and is viewable inside the app.

**Visit model (unchanged from the email design):** a *visit* is a user's time on ONE workspace. It
ends on the first of:
1. explicit **Close workspace** action,
2. **logout**,
3. **session idle expiry**.

On visit end, **notifications are created** (not emailed):
- → **the visiting user's inbox** — memo: ws_id, visit start/end (and session login time), script
  names (+ count), the last search (query / filter / direction), L2 views opened, layout saves made.
- → **the creator's inbox**, only if the visitor ≠ creator — alert: who (username), when, and what
  changed (search replaced, L2s opened, layouts adjusted).

A user visiting N workspaces in one session gets N memos (one per workspace).

**Notification record** (`notifications.json`, per username): `{id, kind: memo|alert, title,
body, read, created_at}`. Title preserves the mailbox-searchable format from the requirement —
`[SQL Data Flow Visualizer] Workspace {ws_id} · {YYYY-MM-DD HH:MM}` — so the inbox list is
searchable/sortable by ws_id and time like a mailbox.

**Pull, not push:** the user sees these on their next login (unread badge + inbox panel). This is
the fundamental consequence of having no email — worth stating plainly.

## 5. Data model (new / extended)

| Store | Contents | Lifecycle |
|-------|----------|-----------|
| `users.json` (new) | `username → {salt, password_hash, created_at}` | Durable |
| `notifications.json` (new) | `username → [notification records]` | Durable |
| `workspaces/{ws_id}/meta.json` (new) | `creator_username`, `created_at`, last-search ref, opened-L2 list with `{script, node_positions}` | Durable, per workspace |
| `workspaces/{ws_id}/activity.json` (new) | append-only event log | Durable, per workspace |
| `sessions` (in-memory) | token → `{username, ws_id open, opened_at, last_active}` | TTL 30 min / on logout |
| existing `views.json` | search views (unchanged) | Durable |

## 6. API additions (draft)

- `POST /api/auth/register`  `{username, password}` (first-time; or merged into login)
- `POST /api/auth/login`  `{username, password}` → sets session cookie
- `POST /api/auth/logout` → destroy session, flush visit memo
- `GET  /api/auth/me` → current username (for UI identity)
- `POST /api/workspace/{ws_id}/close` → end visit, write activity log, create memo (+ creator alert)
- `POST /api/workspace/{ws_id}/search` (existing) → also records layout savepoints per opened L2
- `PUT  /api/workspace/{ws_id}/views/{view_id}/layout` → autosave node positions
- `GET  /api/workspace/{ws_id}/resume` → full current state (L1 + opened L2 + positions) for the resume box
- `GET  /api/notifications` → current user's inbox
- `POST /api/notifications/{id}/read` → mark read
- Workspace **create** records `creator_username` in `meta.json`.

Existing endpoints become auth-gated (session cookie required).

## 7. Frontend additions

- **Login page**: username + password (self-registers unknown usernames); identity shown in top bar.
- **Notification bell** in the top bar: unread badge; inbox panel listing memos/alerts (title, ws_id,
  time, read/unread) — the in-app replacement for the emailed memo.
- **Workspace-id resume box** in the top bar: enter id → load current workspace state (auth-gated).
- **Close workspace** control (explicit visit-end trigger).
- **Opened-L2 strip** under the L1 navigation panel: previously-opened L2s (with saved layouts) —
  click to switch, back to L1; opening an un-saved L2 recomputes fresh and becomes savable.
- **Layout autosave**: on drag-end, debounced (~1 s) PUT of node x/y; silent failure handling.

## 8. Security notes

- Passwords are hashed (salted KDF); never plaintext.
- **Open-by-workspace-id** is the accepted loose access — any logged-in user who knows the id can
  open/edit; the creator is alerted in-app afterwards. (Matches the earlier "simple but a little
  dangerous, use it initially" decision.)
- HttpOnly session cookie; 30-min idle expiry.

## 9. Open items / to confirm

1. **Account provisioning**: self-registration (recommended) vs admin-provisioned user list.
2. **Notification retention**: keep all records vs cap per user (recommend keep — records are small).
3. **Session store lost on container restart** → pending visit memos for that session are lost.
   Acceptable? (Recommend: accept, note it.)
4. **Username convention**: free-form vs keeping `user_name@hsbc.com`-shaped ids for continuity.
5. **Resume of pre-existing workspaces** (created before this feature): no `creator_username` —
   treat as created by "admin"/unknown, or require the first opener to claim them.
