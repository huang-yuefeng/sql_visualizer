# Security Review — Remaining Carried-Forward Items (2026-08-26)

Read-only assessment. No source, test, or config was modified. Verdicts use four states:
**(a) still-present**, **(b) already-fixed**, **(c) accepted-by-design**, **(d) needs a human decision**.

Scope of files read: `backend/app/services/auth_service.py`, `backend/app/services/workspace_service.py`,
`backend/app/services/audit_service.py`, `backend/app/routers/auth.py`, `backend/app/routers/workspace.py`,
`backend/app/routers/dataflow.py`, `backend/app/main.py`, `backend/app/config.py`,
`backend/tests/test_r31_auth.py`, `docker-compose.yml`,
`wiki/USER_IDENTITY_AND_WORKSPACE_EMAILS.md`, `wiki/R31_IMPLEMENTATION.md`.

---

## M-C1 — IDOR on workspace READ (any authenticated user reads any ws_id)

**Verdict: (c) accepted-by-design** — read endpoints enforce no per-workspace membership; that is the
documented sharing model, not an IDOR defect. Flagged here for visibility.

**Evidence — reads are membership-free:**
- `GET /workspace/{ws_id}/resume` — `resume_workspace` (`backend/app/routers/workspace.py:180-207`):
  resolves the session (`_session_ctx`) then **self-serves membership** via `add_workspace_to_index(..., "participant")`
  (line 195). No creator check; any authenticated user who knows the id resumes full L1/L2/layout state.
- `GET /workspace/{ws_id}` — `get_workspace_info` (`workspace.py:93-102`): no `_session_ctx` at all,
  relies only on the login gate (`main.py:246-264`).
- `GET /workspace/{ws_id}/activity` (`workspace.py:218-226`), `GET .../views` (`dataflow.py:261-267`),
  `GET .../views/{vid}/level1` (`dataflow.py:312-357`), `GET .../views/{vid}/level2` (`dataflow.py:360-416`),
  `GET .../scripts/{name}/highlight` (`dataflow.py:419-440`), `GET .../export-config` (`workspace.py:317-323`),
  `GET .../autocomplete` (`workspace.py:371-401`), `POST .../scan` (`workspace.py:229-235`),
  `POST .../index` (`workspace.py:238-274`), `GET .../status` (`workspace.py:278-286`): none perform a
  membership/creator check.
- There is **no** `/workspace/{id}/export` endpoint — the only "export" surface is `export-config`
  (read is unguarded; the PUT/DELETE are creator-gated, see below).

**Why it is by design, not IDOR:**
- `wiki/USER_IDENTITY_AND_WORKSPACE_EMAILS.md` §3 "Sharing model" (lines 85-92): *"Any logged-in user
  who knows the id can open and edit it … `ws_id` is server-generated, high-entropy (UUID4 / 128-bit
  random) — never client-supplied, never sequential — and no endpoint lists workspace ids."*
- `wiki/…_EMAILS.md` §5.5 (line 227): *"Membership = created + opened"* — opening by id adds the opener
  as a participant. `ws_id` is the full 128-bit UUID4 (`workspace_service.py:15,70`, A-H4), unguessable,
  with no enumeration endpoint.
- The authorization split is deliberate: **reads are open by id-possession (capability), writes are
  creator-gated 403.** E.g. layout PUT (`workspace.py:151-155`), filter-config (`workspace.py:309-313`),
  export-config PUT/DELETE (`workspace.py:333-353`), view add/delete (`dataflow.py:277-303`).

Residual note: this is a pure capability model — anyone who learns a `ws_id` (shared link, leaked log,
referrer) can read the whole workspace. That is the intended sharing mechanism, but it is worth keeping
on record that read access has no secondary authorization.

---

## M-C2 — audit log durability (`/tmp/workspaces`)

**Verdict: (a) still-present (residual risk)** — no durability guarantee beyond the container's
volume mount.

**Evidence:**
- `audit.json` (server-global) and `activity.json` (per workspace) are written under
  `WORKSPACE_ROOT = Path("/tmp/workspaces")` (`workspace_service.py:10`; `audit_service.py:57` and `:69`).
- `users.json` (the account store, incl. `workspaces` indexes) also lives there (`auth_service.py:64-65`).
- `docker-compose.yml` mounts `workspace_data:/tmp/workspaces` (named volume), so a *container* restart
  preserves the files — but a **host reboot with a tmpfs-backed `/tmp`** (or a `docker volume rm`) silently
  drops the entire audit trail and account store. Nothing replicates, backs up, or drains these NDJSON
  logs off-box.

Note as residual: audit durability is bounded by the named volume only; no host-reboot/tmpfs protection.

---

## M-C3 — zero-expiry sessions (#279)

**Verdict: (c) accepted-by-design** — confirmed no expiry.

**Evidence:**
- `auth_service.get_session` (`auth_service.py:197-210`): returns the session if present; no `max_age`,
  no idle reaper, no wall-clock check. Docstring (lines 199-203) and module docstring (lines 11-14)
  state ZERO expiry — session lives until logout or server restart.
- Cookie is a session cookie, no `max_age` (`auth.py:72-80`), so the browser drops it on close.
- Settled design is `#279` (module docstring, `auth_service.py:12-14`); sessions lost on restart are
  accepted (A-M9).

---

## L-S2 — failed-login backoff unit test (does the delay actually grow?)

**Verdict: (a) still-present — gap.** No test asserts the backoff delay grows.

**Evidence:**
- The only backoff-adjacent test is `test_login_backoff_async_nonblocking_roundtrip`
  (`backend/tests/test_r31_auth.py:105-114`). It only checks that repeated failed logins still return 401
  and that a subsequent correct login opens a session — it never observes or asserts the delay value.
- A full grep of `backend/tests/` for `record_failed_login`, `_backoff_delay`, `BACKOFF`, `backoff` returns
  only those three lines in `test_r31_auth.py`; there is **no** unit test of
  `_backoff_delay` (`auth_service.py:251-253`) growth or of `record_failed_login` (`auth_service.py:256-271`)
  incrementing per-username/per-IP counters.

Gap: the exponential backoff (base 0.05s, `2^(n-1)`, cap 5s, `_FAILED_LOGIN_CAP=10`) is implemented but
not verified by any assertion.

---

## L-S3 — revoke TOCTOU (`provision_user(force=True)`)

**Verdict: (a) still-present — minor, benign.** The "existed" check and the revoke are not in one
critical section.

**Evidence:**
- `provision_user` (`auth_service.py:116-145`): `_users_lock` spans the whole load→mutate→save of
  `users.json` (lines 127-139), and `existed` is computed inside that lock (line 129).
- But `revoke_user_sessions(username)` is called at line 144 **after** the `with _users_lock` block has
  exited (line 139), and it takes the *session* lock `_lock`, not `_users_lock`.

Consequence: there is a small window between the password write and the session sweep. A login that
completes in that window (with the *new* password) can have its fresh session revoked — a benign UX race.
No *old* session survives the change: `revoke_user_sessions` (`auth_service.py:222-232`) iterates the full
`_sessions` dict at call time and drops every session for the username, so pre-change tokens are always
revoked. No security exposure; note as a non-atomic RMW across two locks.

---

## L-S5 — `_users_lock` held across PBKDF2

**Verdict: (a) still-present — contention note.** The expensive hash runs inside the lock.

**Evidence:**
- `provision_user` calls `_hash_password(password)` at `auth_service.py:132`, inside `with _users_lock`
  (lines 127-139). `_hash_password` (`auth_service.py:104-109`) runs PBKDF2-HMAC-SHA256 at
  `_PBKDF2_ITERATIONS = 600_000` (`auth_service.py:57`).
- The startup force-sync (`main.py:171-172`) provisions **every** `PROVISIONED_USERS` entry with
  `force=True`, so each deploy serially hashes under `_users_lock`.

Contention implication: any other `_users_lock` consumer blocks for the hash duration — e.g. login's
`last_login_ip` write (`auth_service.py:181-187`) and every index operation (`add_workspace_to_index` etc.
at lines 296-342). Login's PBKDF2 **verify** runs *outside* the lock (`auth_service.py:168-177`), so the
main cost is serialized provisioning at startup, not the login hot path. Single uvicorn worker + low
concurrency keeps practical impact low, but the lock scope is wider than it needs to be (hash could run
outside the lock, with the RMW re-checking under the lock).

---

## L-C1 — CORS `*` + credentials

**Verdict: (a) still-present — residual (defense-in-depth), not exploitable in the current model.**

**Evidence:**
- `config.py:24` — `CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*").split(",")` → default `["*"]`.
- `main.py:190-196` — `CORSMiddleware(allow_origins=CORS_ORIGINS, allow_credentials=True,
  allow_methods=["*"], allow_headers=["*"])`.
- Starlette 1.3.1 (installed) behavior: with `allow_all_origins=True` **and** `allow_credentials=True`,
  `send()` reflects the request `Origin` into `Access-Control-Allow-Origin` and adds `Vary: Origin`
  (`preflight_explicit_allow_origin = not allow_all_origins or allow_credentials`; verified against the
  installed middleware source). Net effect: **any** origin is treated as allowed with credentials — the
  classic "wildcard + credentials" footgun.

Mitigating factors (why it is residual, not active):
- Session cookie is `SameSite=Lax` (`auth.py:79`) — a cross-site `fetch`/XHR does not carry the session
  cookie, so credentialed cross-origin reads are blocked at the cookie layer.
- `login_gate` middleware (`main.py:246-264`) rejects state-changing requests whose `Origin`/`Referer`
  does not match `Host` (403) — a same-origin check for POST/PUT/DELETE/PATCH.
- Deployment is a single-origin offline model (SPA served from the same FastAPI origin at `/`), so there
  is no legitimate cross-origin consumer.

Recommendation (note only): pin `CORS_ORIGINS` to the specific service origin rather than `*` so the
credentialed CORS posture cannot be silently widened by a future cookie/config change.

---

## H-S2 — hardcoded `admin@hsbc.com / 123456`

**Verdict: FLAG ONLY (product decision — not changed).**

**Exact location:** `backend/app/config.py:42`
```python
PROVISIONED_USERS = {"admin@hsbc.com": "123456"}
```
Also referenced in `backend/app/services/auth_service.py:52-56` (the 6-char-min rationale that keeps this
account working) and asserted by `backend/tests/test_r31_auth.py:123-129`. It is force-synced into
`users.json` on every deploy (`main.py:171-172`). There is no HTTP path to change it; it is the default
production admin credential baked into the image.

**One-line recommendation:** rotate this default to a strong, env-injected secret (`PROVISIONED_USERS_JSON`)
for any real deployment — the current default is a publicly-known credential in the offline single-admin
model.

---

## Summary

| Item | Verdict | File:line (key) |
|------|---------|-----------------|
| M-C1 IDOR read | (c) accepted-by-design | `workspace.py:180-207`, `dataflow.py:261/312/360`, wiki §3/§5.5 |
| M-C2 audit durability | (a) residual risk | `workspace_service.py:10`, `audit_service.py:57,69` |
| M-C3 zero-expiry sessions | (c) accepted-by-design | `auth_service.py:197-210`, `auth.py:72-80` |
| L-S2 backoff unit test | (a) gap (untested growth) | `test_r31_auth.py:105-114` only |
| L-S3 revoke TOCTOU | (a) minor/benign | `auth_service.py:127-145` |
| L-S5 lock across PBKDF2 | (a) contention note | `auth_service.py:127-139,132` |
| L-C1 CORS `*` + creds | (a) residual (mitigated) | `config.py:24`, `main.py:190-196` |
| H-S2 hardcoded admin | FLAG only | `config.py:42` |

Closed/accepted: **M-C1** and **M-C3** are settled design decisions with in-code citations.
Open (carried forward as residual/gap, no code change made): **M-C2** (durability), **L-S2** (missing
unit test), **L-S3** (benign TOCTOU), **L-S5** (lock scope), **L-C1** (wildcard CORS).
Flagged for a human/product decision: **H-S2** (hardcoded default admin credential).
