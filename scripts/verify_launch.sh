#!/usr/bin/env bash
set -euo pipefail

# ── Lycan-Data Launch Verification ──────────────────────────────────────────
# Starts docker-compose, waits for health, runs migrations, executes a real
# search, and reports success or failure.
# ────────────────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$ROOT_DIR"

# Load .env for API key
if [ -f .env ]; then
    # shellcheck disable=SC2046
    export $(grep -v '^#' .env | grep -v '^$' | xargs)
fi

API_KEY="${API_KEYS%%,*}"  # first key from comma-separated list
API_URL="http://localhost:8000"
MAX_WAIT=60
POLL_INTERVAL=5

fail() {
    echo ""
    echo "FAILED at step: $1"
    echo "  $2"
    exit 1
}

echo "========================================"
echo "Lycan-Data Launch Verification"
echo "========================================"

# ── Step 1: Start docker-compose ───────────────────────────────────────────
echo ""
echo "[1/4] Starting docker-compose..."
docker compose up -d 2>&1 || fail "docker-compose up" "Could not start services"
echo "  Services started."

# ── Step 2: Wait for health ────────────────────────────────────────────────
echo ""
echo "[2/4] Waiting for API health (max ${MAX_WAIT}s)..."
elapsed=0
healthy=false

while [ "$elapsed" -lt "$MAX_WAIT" ]; do
    status=$(curl -sf "${API_URL}/system/health" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")
    if [ "$status" = "ok" ] || [ "$status" = "degraded" ]; then
        healthy=true
        break
    fi
    echo "  Waiting... (${elapsed}s / ${MAX_WAIT}s)"
    sleep "$POLL_INTERVAL"
    elapsed=$((elapsed + POLL_INTERVAL))
done

if [ "$healthy" = false ]; then
    fail "health check" "API did not become healthy within ${MAX_WAIT}s"
fi
echo "  API healthy after ${elapsed}s (status: ${status})"

# ── Step 3: Run migrations ─────────────────────────────────────────────────
echo ""
echo "[3/4] Running alembic migrations..."
if [ -f .venv/bin/python ]; then
    .venv/bin/python -m alembic upgrade head 2>&1 || fail "alembic upgrade" "Migration failed"
else
    alembic upgrade head 2>&1 || fail "alembic upgrade" "Migration failed"
fi
echo "  Migrations complete."

# ── Step 4: Execute a real search ──────────────────────────────────────────
echo ""
echo "[4/4] Running test search: John Smith..."
response=$(curl -sf -X POST "${API_URL}/search" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer ${API_KEY}" \
    -d '{"value": "John Smith"}' 2>&1) || fail "search request" "POST /search failed — is the API key correct?"

echo "  Response:"
echo "$response" | python3 -m json.tool 2>/dev/null || echo "$response"

# ── Done ───────────────────────────────────────────────────────────────────
echo ""
echo "========================================"
echo "Launch verification PASSED"
echo "========================================"
exit 0
