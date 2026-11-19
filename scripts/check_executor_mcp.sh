#!/usr/bin/env bash
# Check that the Executor MCP endpoint (POST /mcp) answers, with curl.
#
# The Executor serves MCP Streamable HTTP in stateless JSON mode, so a single
# tools/list works without initialize. It is authenticated by the same
# middleware as REST: X-Api-Key is required, X-Tenant-Id may be omitted when
# the key has a default tenant, and X-User-Id is only needed for tool calls
# that act for a user. The Accept header must name both types or the server
# answers 406. A 404 means MCP_ENABLED is false there (stg, prd), and a
# rejected Host means it is missing from the Executor's MCP_ALLOWED_HOSTS.
#
# Usage:
#   EXECUTOR_BASE_URL=http://127.0.0.1:8000 EXECUTOR_API_KEY=... \
#   [EXECUTOR_TENANT_ID=dtest-agent-service] [EXECUTOR_USER_ID=ita0001] \
#   scripts/check_executor_mcp.sh [tool-name]
#
# With a tool name it also calls that tool with empty arguments, for example
# execution_list.
set -u

: "${EXECUTOR_API_KEY:?set EXECUTOR_API_KEY}"
BASE="${EXECUTOR_BASE_URL:-http://localhost:8000}"
URL="${BASE%/}/mcp"
TOOL="${1:-}"

HEADERS=(
  -H "Content-Type: application/json"
  -H "Accept: application/json, text/event-stream"
  -H "X-Api-Key: $EXECUTOR_API_KEY"
)
[ -n "${EXECUTOR_TENANT_ID:-}" ] && HEADERS+=(-H "X-Tenant-Id: $EXECUTOR_TENANT_ID")
[ -n "${EXECUTOR_USER_ID:-}" ] && HEADERS+=(-H "X-User-Id: $EXECUTOR_USER_ID")

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
FAILED=0

run() {
  local name="$1" body="$2"
  printf '%s\n' "$body" > "$TMP/body.json"
  echo "=== $name"
  local code
  code=$(curl -sS -o "$TMP/out" -w '%{http_code}' -X POST "$URL" \
    "${HEADERS[@]}" --data-binary @"$TMP/body.json")
  echo "    HTTP $code"
  [ "$code" = "200" ] || FAILED=1
  if [ "$code" = "200" ] && command -v python3 >/dev/null; then
    python3 - "$TMP/out" <<'PY' || FAILED=1
import json, sys
data = json.load(open(sys.argv[1]))
if "error" in data:
    print(f"    JSON-RPC error: {data['error']}")
    sys.exit(1)
result = data["result"]
if "tools" in result:
    names = [tool["name"] for tool in result["tools"]]
    print(f"    {len(names)} tools: {', '.join(names)}")
else:
    print(f"    isError={result.get('isError', False)}")
    print("    " + json.dumps(result, ensure_ascii=False)[:600])
    sys.exit(1 if result.get("isError") else 0)
PY
  else
    head -c 600 "$TMP/out"; echo
  fi
}

echo "POST $URL"
run "tools/list" '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
if [ -n "$TOOL" ]; then
  run "tools/call $TOOL" \
    "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/call\",\"params\":{\"name\":\"$TOOL\",\"arguments\":{}}}"
fi
exit "$FAILED"
