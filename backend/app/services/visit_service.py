"""R31 visit-end flush: activity-log entry + memo (+ creator alert).

Settled design: wiki/USER_IDENTITY_AND_WORKSPACE_EMAILS.md (§5.4, A-M10) +
wiki/R31_IMPLEMENTATION.md (§4).

A visit ends on workspace close / logout / session idle expiry. Flush is
PER SESSION; the memo/creator-alert is AGGREGATED PER USER — created only
when the last of that user's sessions closes the workspace. Memos carry the
username (self-describing, A-M10).
"""

from app.services import auth_service
from app.services.audit_service import append_activity
from app.services.notification_service import add_creator_alert, add_memo
from app.services.workspace_service import read_meta


def _memo_body(username: str, ws_id: str, opened_at: str | None,
               ip: str, detail: str) -> str:
    return (
        f"Workspace {ws_id} visit closed.\n"
        f"Username: {username}\n"
        f"Session IP: {ip}\n"
        f"Opened: {opened_at or 'unknown'}\n"
        f"{detail}"
    )


def flush_session_visits(token: str, detail: str = "") -> int:
    """Flush one session's open visits (logout/expiry/close-all).

    For each open ws_id: write the activity-log visit-end, then create the
    memo for the visitor and an alert for the creator (when the visitor is
    not the creator) — each ONLY if no other session of the same username
    still has the workspace open (A-M10). Returns the number of memos/alerts
    created.
    """
    visits = auth_service.flush_session_visits(token)
    created = 0
    for v in visits:
        username = v["username"]
        ip = v["ip"]
        ws_id = v["ws_id"]
        opened_at = v.get("opened_at")
        append_activity(ws_id, username, ip, "visit_end",
                        f"{username} closed workspace {ws_id}" + (f" ({detail})" if detail else ""))
        if auth_service.other_sessions_have_visit(username, ws_id, except_token=token):
            continue  # another of this user's sessions still has it open
        meta = read_meta(ws_id) or {}
        creator = meta.get("creator_username")
        memo = add_memo(username, ws_id, _memo_body(username, ws_id, opened_at, ip, detail))
        created += 1
        if creator and creator != username:
            add_creator_alert(
                creator, ws_id,
                f"{username} ({ip}) worked on your workspace {ws_id} and closed it.\n{detail}"
            )
            created += 1
    return created
