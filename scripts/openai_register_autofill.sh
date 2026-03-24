#!/usr/bin/env bash
set -euo pipefail

# Auto-fill token pool for deploy-cli-proxy.
# Runs register_with_password.py only when token/codex file count is below target.
#
# Default timezone expectation: Asia/Shanghai (UTC+8) for logs/cron.

AUTH_DIR="${AUTH_DIR:-/home/ubuntu/github/deploy-cli-proxy/auths}"
REGISTER_DIR="${REGISTER_DIR:-/home/ubuntu/.openclaw/workspace/openai-register}"
PY_BIN="${PY_BIN:-$REGISTER_DIR/.venv/bin/python}"

TARGET_COUNT="${TARGET_COUNT:-200}"
MAX_PER_RUN="${MAX_PER_RUN:-20}"   # safety cap per hourly run
SLEEP_MIN="${SLEEP_MIN:-30}"
SLEEP_MAX="${SLEEP_MAX:-120}"

LOCK_FILE="${LOCK_FILE:-/tmp/openai_register_autofill.lock}"
LOG_PREFIX="[openai_register_autofill]"

count_tokens() {
  # token_*.json and codex*.json
  find "$AUTH_DIR" -maxdepth 1 -type f \( -name 'token_*.json' -o -name 'codex*.json' \) 2>/dev/null | wc -l | tr -d ' '
}

main() {
  if [[ ! -d "$AUTH_DIR" ]]; then
    echo "$LOG_PREFIX auth dir missing: $AUTH_DIR" >&2
    exit 1
  fi
  if [[ ! -d "$REGISTER_DIR" ]]; then
    echo "$LOG_PREFIX register dir missing: $REGISTER_DIR" >&2
    exit 1
  fi
  if [[ ! -x "$PY_BIN" ]]; then
    echo "$LOG_PREFIX python venv missing/not executable: $PY_BIN" >&2
    exit 1
  fi

  # Prevent overlapping hourly runs.
  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    echo "$LOG_PREFIX lock busy, skip"
    exit 0
  fi

  local current
  current="$(count_tokens)"

  if (( current >= TARGET_COUNT )); then
    echo "$LOG_PREFIX ok: token/codex count=$current (>= $TARGET_COUNT), skip"
    exit 0
  fi

  local need
  need=$(( TARGET_COUNT - current ))

  local max_count
  max_count="$need"
  if (( max_count > MAX_PER_RUN )); then
    max_count="$MAX_PER_RUN"
  fi

  echo "$LOG_PREFIX low: token/codex count=$current (< $TARGET_COUNT), will register max_count=$max_count (need=$need)"

  cd "$REGISTER_DIR"

  # register_with_password.py will load .env from this directory.
  exec "$PY_BIN" register_with_password.py \
    --sleep-min "$SLEEP_MIN" \
    --sleep-max "$SLEEP_MAX" \
    --max-count "$max_count"
}

main "$@"
