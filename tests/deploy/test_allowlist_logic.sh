#!/usr/bin/env bash
# Tests for target_deploy.sh's user-allowlist loading (build_users_env).
#
# Plain bash, no framework: source the deploy script (its entry guard makes a
# sourced run define the functions and run NOTHING), call the function against
# fixture files, count failures. Prints PASS/FAIL per case and exits non-zero
# if any case fails.
#
# Run:  bash tests/deploy/test_allowlist_logic.sh
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
DEPLOY_SCRIPT="$REPO_ROOT/target_deploy.sh"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
# Testability seam: keep the deploy's diagnostics out of the real deploy log.
export DEPLOY_LOG_FILE="$WORK/deploy-test.log"

# shellcheck source=/dev/null
source "$DEPLOY_SCRIPT"

PASS=0
FAIL=0

pass() { PASS=$((PASS+1)); echo "  PASS: $1"; }
fail() { FAIL=$((FAIL+1)); echo "  FAIL: $1"; if [ "$#" -gt 1 ]; then echo "        $2"; fi; return 0; }

# check <label> <expected> <actual>
check() {
    if [ "$2" = "$3" ]; then
        pass "$1"
    else
        fail "$1" "expected [$2] got [$3]"
    fi
}

# fixture <name> <content...>  → echo the fixture path
fixture() {
    local f="$WORK/$1"; shift
    printf '%s' "$*" > "$f"
    printf '%s' "$f"
}

# run_build <path> → sets OUT and GOT_STATUS.
# The function is called BARE, exactly as target_deploy.sh calls it: capturing
# stdout here (`out="$(build_users_env …)")` would run it in a subshell and
# lose USERS_ENV_STATUS — case 11 pins that trap explicitly.
run_build() {
    build_users_env "$1" >/dev/null
    OUT="$USERS_ENV_JSON"
    GOT_STATUS="$USERS_ENV_STATUS"
}

echo "== build_users_env (target_deploy.sh) =="

# 1. admin already present → ok, payload passed through untouched
F="$(fixture a_admin_present.json '{"admin@hsbc.com":"s3cret-pw","alice@hsbc.com":"alice-pw"}')"
run_build "$F"
check "admin-present: status" "ok" "$GOT_STATUS"
check "admin-present: payload untouched" \
    '{"admin@hsbc.com":"s3cret-pw","alice@hsbc.com":"alice-pw"}' "$OUT"

# 2. admin omitted → merged-admin, admin first with the default password
F="$(fixture b_admin_merged.json '{"alice@hsbc.com":"alice-pw2","bob@hsbc.com":"bob-pw3"}')"
run_build "$F"
check "admin-merged: status" "merged-admin" "$GOT_STATUS"
check "admin-merged: payload" \
    '{"admin@hsbc.com":"123456","alice@hsbc.com":"alice-pw2","bob@hsbc.com":"bob-pw3"}' "$OUT"

# 3. full-line // comments stripped (pretty-printed file, admin omitted)
F="$WORK/c_comments.json"
cat > "$F" <<'EOF'
// production accounts
{
    // admin keeps the default password
    "alice@hsbc.com": "alice-pw2",
    "bob@hsbc.com": "bob-pw3"
}
EOF
run_build "$F"
check "comments: status" "merged-admin" "$GOT_STATUS"
case "$OUT" in
    '{"admin@hsbc.com":"123456",'* ) pass "comments: admin merged first";;
    * ) fail "comments: admin merged first" "got [$OUT]";;
esac
case "$OUT" in
    *'//'* ) fail "comments: no comment text leaks into the payload" "got [$OUT]";;
    * ) pass "comments: no comment text leaks into the payload";;
esac
# and the payload must be the semantically correct object
if command -v python3 >/dev/null 2>&1; then
    GOT_DICT="$(printf '%s' "$OUT" | python3 -c 'import json,sys;print(json.dumps(json.load(sys.stdin),sort_keys=True))')"
    check "comments: payload parses to the expected object" \
        '{"admin@hsbc.com": "123456", "alice@hsbc.com": "alice-pw2", "bob@hsbc.com": "bob-pw3"}' \
        "$GOT_DICT"
else
    echo "  SKIP: comments payload semantic check (python3 not available)"
fi

# 3b. a `//` inside a VALUE (https://…) is not treated as a comment
F="$(fixture c2_url_value.json '{"alice@hsbc.com":"pw12345","note@hsbc.com":"https://example.com/x"}')"
run_build "$F"
check "https-value: status" "merged-admin" "$GOT_STATUS"
case "$OUT" in
    *'https://example.com/x'*) pass "https-value: '//' inside a value preserved";;
    * ) fail "https-value: '//' inside a value preserved" "got [$OUT]";;
esac

# 3c. SPACES are legal JSON whitespace and may belong to a password — the
#     comment strip removes CR/LF/TAB only, never a space inside a value.
F="$(fixture c3_space_password.json '{"carol@hsbc.com":"pa ss word"}')"
run_build "$F"
check "space-password: status" "merged-admin" "$GOT_STATUS"
case "$OUT" in
    *'"carol@hsbc.com":"pa ss word"'*) pass "space-password: interior space preserved";;
    * ) fail "space-password: interior space preserved" "got [$OUT]";;
esac

# 4. empty file → skip (image default, admin only)
F="$(fixture d_empty.json '')"
run_build "$F"
check "empty-file: status" "empty-file" "$GOT_STATUS"
check "empty-file: no payload" "" "$OUT"

# 4b. comments only → nothing left to parse, same skip
F="$(fixture d2_comments_only.json '// nothing but comments
// still nothing')"
run_build "$F"
check "comments-only: status" "empty-file" "$GOT_STATUS"

# 5. invalid JSON → skip
F="$(fixture e_invalid.json '{"alice@hsbc.com":"pw12345"')"
run_build "$F"
check "invalid-json: status" "invalid-json" "$GOT_STATUS"
check "invalid-json: no payload" "" "$OUT"

F="$(fixture e2_garbage.json 'not json at all')"
run_build "$F"
check "garbage: status" "invalid-json" "$GOT_STATUS"

# 5b. trailing comment after the JSON on the SAME line is NOT supported —
#     documented limitation: it must fail validation, never pass silently.
F="$(fixture e3_trailing_comment.json '{"alice@hsbc.com":"pw12345"} // trailing note')"
run_build "$F"
check "trailing-comment: status" "invalid-json" "$GOT_STATUS"

# 5c. shape-valid but syntactically broken (missing comma) is caught by the
#     deep parse when python3 exists; without it the shape check is all we have.
if command -v python3 >/dev/null 2>&1; then
    F="$(fixture e4_missing_comma.json '{"alice@hsbc.com":"pw12345" "bob@hsbc.com":"pw67890"}')"
    run_build "$F"
    check "missing-comma: status" "invalid-json" "$GOT_STATUS"
else
    echo "  SKIP: missing-comma case (python3 not available — shape check only)"
fi

# 6. {} — valid JSON that provisions nothing → skip, admin-only default
F="$(fixture f_empty_object.json '{}')"
run_build "$F"
check "empty-object: status" "empty-object" "$GOT_STATUS"
check "empty-object: no payload" "" "$OUT"

# 6b. pretty-printed {} (whitespace only around the braces)
F="$WORK/f2_empty_object_pretty.json"
printf '{\n}\n' > "$F"
run_build "$F"
check "empty-object-pretty: status" "empty-object" "$GOT_STATUS"

# 7. no file → skip (fresh target machine, image default)
run_build "$WORK/does-not-exist.json"
check "no-file: status" "no-file" "$GOT_STATUS"
check "no-file: no payload" "" "$OUT"

run_build ""
check "no-arg: status" "no-file" "$GOT_STATUS"

# 8. set -e safety: a bad file must be a status, never an abort. This test
#    runs under the `set -e` the deploy script installs when sourced — if
#    build_users_env ever returned non-zero, the next line would not run.
F="$(fixture g_sete.json '{"broken')"
run_build "$F"
check "set-e-safe: still running after an invalid file" "invalid-json" "$GOT_STATUS"

# 9. stdout is the payload only — diagnostics went to stderr + the log file
F="$(fixture h_diag.json '{"alice@hsbc.com":"pw12345"}')"
ERR_FILE="$WORK/stderr.txt"
CAPTURED="$(build_users_env "$F" 2>"$ERR_FILE")"
check "stdout: the payload is printed (composable)" \
    '{"admin@hsbc.com":"123456","alice@hsbc.com":"pw12345"}' "$CAPTURED"
case "$CAPTURED" in
    *'Users:'*|*'⚠'*) fail "stdout purity: no log noise on stdout" "got [$CAPTURED]";;
    * ) pass "stdout purity: no log noise on stdout";;
esac
if grep -q "provisioning allowlist from" "$ERR_FILE"; then
    pass "diagnostics: message reached stderr"
else
    fail "diagnostics: message reached stderr" "stderr was [$(cat "$ERR_FILE")]"
fi
if grep -q "provisioning allowlist from" "$DEPLOY_LOG_FILE"; then
    pass "diagnostics: message reached the deploy log"
else
    fail "diagnostics: message reached the deploy log" ""
fi

# 10. the entry guard: sourcing defined the functions WITHOUT executing the
#     deploy (no "Version guard" section in this run's log)
if grep -q "=== Version guard ===" "$DEPLOY_LOG_FILE"; then
    fail "entry-guard: a sourced run executes no deploy steps" ""
else
    pass "entry-guard: a sourced run executes no deploy steps"
fi
if type build_users_env >/dev/null 2>&1; then
    pass "entry-guard: build_users_env is defined after sourcing"
else
    fail "entry-guard: build_users_env is defined after sourcing" ""
fi

# 11. THE SUBSHELL TRAP: a captured call (`x="$(build_users_env …)")` runs the
#     function in a subshell, so the status it sets NEVER reaches the caller —
#     the caller's copy keeps its old value. That is exactly why
#     target_deploy.sh calls the function bare. If the deploy ever regresses to
#     a captured call, nothing would ever be provisioned and this case is the
#     only place that says why.
USERS_ENV_STATUS="sentinel"
CAPTURED="$(build_users_env "$F" 2>/dev/null)"
check "subshell-trap: a captured call cannot set the caller's status" "sentinel" "$USERS_ENV_STATUS"
run_build "$F"
check "subshell-trap: the deploy's bare call gets the status" "merged-admin" "$GOT_STATUS"
check "subshell-trap: the deploy's bare call gets the payload" \
    '{"admin@hsbc.com":"123456","alice@hsbc.com":"pw12345"}' "$OUT"

echo
echo "allowlist logic: $PASS passed, $FAIL failed"
if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
exit 0
