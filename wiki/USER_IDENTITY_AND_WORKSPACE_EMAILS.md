# User Identity, Workspace Lifecycle Emails & Layout-Resume Collaboration

> Design note — agreed 2026-08-14. No code changed. Status: **discussion settled; awaiting SMTP connection details from the user.**

## 1. Purpose

Make the SQL Data Flow Visualizer a multi-user service where:

1. Users identify themselves by their HSBC postfix email (`user_name@hsbc.com`) and log in via a one-time password sent to that mailbox (no stored passwords).
2. Work is organized by **workspace id** — the shared unit of state.
3. When a user finishes a workspace, the system emails that user a **memo** of what happened on that workspace; if the user is not the workspace's **creator**, the creator additionally gets an **alert**.
4. A user can resume a previous workspace by entering its id, restoring the full current state **including manually-adjusted L1/L2 layouts** — the layout work is the user's main contribution and must survive.

Environment: the target machine is on a strictly managed network — **no random internet access**, but the internal `@hsbc.com` mail path is usable. All email (OTP, memos, alerts) goes through that internal path only.

## 2. Agreed decisions (Q&A summary)

| # | Question | Decision |
|---|----------|----------|
| — | Logout mechanism | **Idle timeout (30 min)**; also a logout button. Email flush triggers are workspace close / session expiry / logout. |
| — | One L1 + multiple L2 | Keep. One search = one L1; the L2s the user opened are retained. |
| Q1 | Email delivery | Yes — SMTP to any address incl. `@hsbc.com`. **Blocker: SMTP host/port/auth/from-address to be provided.** |
| Q2 | Last-search state | **Shared**, workspace-wide. Resume = current workspace state, never a personal history. Last-writer (the one who closes last) wins. |
| Q3 | Access model | **Open by workspace id** — any logged-in user who knows the id can open and edit; creator is only notified. (Known simple, slight risk, accepted for now.) |
| Q4 | Multiple L2 + layout save | (b) Only the L2 views the user actually **opened** are retained. **Autosave on each drag-end.** Save **node x/y only**; zoom/pan ignored. |
| Q5 | Concurrent users | **Last-write-wins**, no locking/version stamps. |
| Q6 | Accounts | **Auto-create any `*@hsbc.com`**, and **never persist** — account info is discarded when the session ends. OTP ~10 min, single-use, resend cooldown. |
| Q7 | Email content | One email per workspace-close. **No script contents** — script names, search table/field names, ws_id, time. Enough to understand what happened. |
| Q8 | Idle timeout | **30 minutes**. Memo sent on workspace close / session expiry / logout. |

## 3. Model

### 3.1 Identity & login (ephemeral accounts)
- User enters `user_name@hsbc.com` on the login page.
- Backend generates a random one-time password (OTP), stores it server-side (TTL ≈ 10 min, single-use, resend cooldown), and emails it to that address.
- User types the OTP back; backend verifies, creates a **session**, returns an `HttpOnly` session cookie.
- **No user table.** Identity is never persisted beyond the session. Every login is a fresh OTP. (Workspace history is the durable record — section 3.3.)

### 3.2 Sessions
- Server-side sessions keyed by an opaque token in an `HttpOnly` cookie (not readable by JS).
- **Idle timeout 30 min** — activity extends it; on expiry the session is destroyed and pending workspace memos flush.
- Explicit **logout** button ends the session immediately (same flush).
- Session store is in-memory (lost on container restart — acceptable edge case; note in docs).

### 3.3 Workspace state (shared, durable)
- A workspace = `WORKSPACE_ROOT/{ws_id}/` (existing) plus a **workspace metadata record**:
  - `creator_email` (the email that created it — fixed at creation)
  - `created_at`
  - the **last search state**: exactly one L1 (the search) + the list of **opened L2 views**, each with its **persisted node x/y layout**
- **Last search is shared and current-state-only.** A new search by anyone replaces the stored one. Resume by ws_id shows the current state, not history. Last-writer-wins on every write (no locking).
- **Layout persistence:** the frontend reports node x/y on each drag-end (debounced autosave); backend stores per-view `{node_id: [x,y]}`. On resume, positions are re-applied instead of recomputed. Zoom/pan intentionally not saved.

### 3.4 Emails (per workspace-visit)
Unit of email = **a user's visit to one workspace**. A visit ends on the first of:
1. explicit **Close workspace** action,
2. **logout**,
3. **session idle expiry**.

On visit end, **one email** is sent per workspace:
- → **the visiting user's inbox** — memo: ws_id, visit start/end (and session login time), script names (+ count), the last search (query / filter / direction), L2 views opened, layout saves made.
- → **the creator's inbox**, only if the visitor ≠ creator — alert: who (email), when, and what changed in the workspace (search replaced, L2s opened, layouts adjusted).

A user visiting N workspaces in one session gets N memos (one per workspace) — matches "creates many workspaces → multiple emails".

**Subject format (as requested):** `[SQL Data Flow Visualizer] Workspace {ws_id} · {YYYY-MM-DD HH:MM}` — system name + workspace id + time, so users can search their mailboxes.

**Content rule:** no script contents, no full SQL. Script names + search table/field names + ws_id + times only.

## 4. Data model (new / extended)

| Store | Contents | Lifecycle |
|-------|----------|-----------|
| `workspaces/{ws_id}/meta.json` (new) | `creator_email`, `created_at`, last-search ref, opened-L2 list with `{script, node_positions}` | Durable, per workspace |
| `sessions` (in-memory) | token → `{user_email, ws_id(s) open, opened_at, last_active}` | TTL 30 min / on logout |
| `otps` (in-memory) | `email → {code_hash, expires_at, attempts}` | TTL ~10 min, single-use |

Extends the existing `views.json` (search views) rather than replacing it: the last-search view stays in views.json; `meta.json` adds creator + layout positions + opened-L2 registry.

## 5. API additions (draft)

- `POST /api/auth/request_otp`  `{email}` → emails OTP (rate-limited)
- `POST /api/auth/login`  `{email, otp}` → sets session cookie
- `POST /api/auth/logout` → destroy session, flush memos
- `GET  /api/auth/me` → current user email (for UI identity)
- `POST /api/workspace/{ws_id}/close` → end visit, send memo (+ creator alert)
- `POST /api/workspace/{ws_id}/search` (existing) → also records layout savepoints per opened L2
- `PUT  /api/workspace/{ws_id}/views/{view_id}/layout` → autosave node positions
- `GET  /api/workspace/{ws_id}/resume` → full current state (L1 + opened L2 + positions) for the resume box
- Workspace **create** records `creator_email` in `meta.json`.

Existing endpoints become auth-gated (session cookie required).

## 6. Frontend additions

- **Login page**: email + OTP fields; identity shown in top bar.
- **Workspace-id resume box** in the top bar: enter id → load current workspace state (auth-gated).
- **Close workspace** control (explicit visit-end trigger).
- **Opened-L2 strip** under the L1 navigation panel: previously-opened L2s (with saved layouts) — click to switch, back to L1; opening an un-saved L2 recomputes fresh and becomes savable.
- **Layout autosave**: on drag-end, debounced (~1 s) PUT of node x/y; silent failure handling.

## 7. Email transport — BLOCKER

- Mechanism: Python `smtplib` (or `sendmail`/`mailx` binary if the target has it configured).
- **Awaiting from user:** SMTP host + port, SSL/STARTTLS, auth credentials, from-address, and confirmation the container can reach the SMTP host over the managed network.
- Constraint: **only the internal `@hsbc.com` mail path**; nothing may touch the open internet (standing offline rule).

## 8. Open items / to verify on the target machine

1. **SMTP connection details** (the blocker above) — user to provide.
2. Whether the Docker container can reach the SMTP host (compose network / DNS).
3. Whether `sendmail`/`mailx` is already configured on the target host (alternative to smtplib).
4. OTP delivery failure fallback: show OTP in server log / API response for demo continuity (recommended) vs hard block — user to confirm.
5. Session store lost on container restart → pending memos for that session are lost. Acceptable? (Recommend: accept, note it.)
