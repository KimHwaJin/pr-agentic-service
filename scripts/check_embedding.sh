#!/usr/bin/env bash
# Check the embedding gateway (EMBEDDING_PROVIDER=openai) with curl.
#
# The service calls it through langchain_openai.OpenAIEmbeddings, which posts
#   {"model": ..., "input": [..], "dimensions": EMBEDDING_DIMS,
#    "encoding_format": "base64"}
# to $EMBEDDING_BASE_URL/embeddings. Each case below adds one of those fields
# to a minimal request, so the first failing case names the field the gateway
# rejects. Bodies go through files, never inline -d, so pasted quotes cannot
# break the JSON.
#
# Usage:
#   EMBEDDING_BASE_URL=http://model.frodo.com/v1 \
#   EMBEDDING_API_KEY=... EMBEDDING_MODEL=bge-m3 EMBEDDING_DIMS=1024 \
#   scripts/check_embedding.sh ["test text"]
set -u

: "${EMBEDDING_BASE_URL:?set EMBEDDING_BASE_URL (up to /v1)}"
: "${EMBEDDING_MODEL:?set EMBEDDING_MODEL}"
KEY="${EMBEDDING_API_KEY:-EMPTY}"
DIMS="${EMBEDDING_DIMS:-1024}"
TEXT="${1:-매출 추이 분석}"
URL="${EMBEDDING_BASE_URL%/}/embeddings"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

run() {
  local name="$1" body="$2"
  printf '%s\n' "$body" > "$TMP/body.json"
  echo "=== $name"
  echo "    body: $body"
  local code
  code=$(curl -sS -o "$TMP/out" -w '%{http_code}' "$URL" \
    -H "Authorization: Bearer $KEY" \
    -H "Content-Type: application/json" \
    --data-binary @"$TMP/body.json")
  echo "    HTTP $code"
  if [ "$code" = "200" ] && command -v python3 >/dev/null; then
    python3 - "$TMP/out" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))["data"][0]["embedding"]
if isinstance(data, str):
    import base64
    print(f"    base64 embedding, {len(base64.b64decode(data)) // 4} dims")
else:
    print(f"    float embedding, {len(data)} dims")
PY
  else
    head -c 400 "$TMP/out"; echo
  fi
}

echo "POST $URL (model=$EMBEDDING_MODEL, dims=$DIMS)"
run "1 minimal, input string" \
  "{\"model\": \"$EMBEDDING_MODEL\", \"input\": \"$TEXT\"}"
run "2 input array (the service always sends an array)" \
  "{\"model\": \"$EMBEDDING_MODEL\", \"input\": [\"$TEXT\"]}"
run "3 + dimensions" \
  "{\"model\": \"$EMBEDDING_MODEL\", \"input\": [\"$TEXT\"], \"dimensions\": $DIMS}"
run "4 exactly what the service sends (+ encoding_format base64)" \
  "{\"model\": \"$EMBEDDING_MODEL\", \"input\": [\"$TEXT\"], \"dimensions\": $DIMS, \"encoding_format\": \"base64\"}"
echo
echo "The embedding length must equal EMBEDDING_DIMS ($DIMS) for pgvector search."
