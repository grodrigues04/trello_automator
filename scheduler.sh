#!/usr/bin/env bash
# Checks the wall clock every 30 seconds and starts a session in the first 10 minutes of
# Monday 12:00, Thursday 22:30 and Friday 22:00. A computer that is off or suspended in the
# window misses that session: there is no catch-up.
set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
STATE_DIR="$PROJECT_DIR/data/state"
mkdir -p "$STATE_DIR"

# git and gh use GH_TOKEN: the remote of ratUFSC is SSH, rewritten to HTTPS here
gh auth setup-git
git config --global url."https://github.com/".insteadOf "git@github.com:"
git config --global --add safe.directory '*'

echo "[scheduler] started at $(date '+%F %T %Z'): Mon 12:00, Thu 22:30, Fri 22:00"

is_session_window() {
  local day_of_week minutes
  day_of_week=$(date +%u)
  minutes=$((10#$(date +%H) * 60 + 10#$(date +%M)))
  case "$day_of_week" in
    1) [ "$minutes" -ge $((12 * 60)) ] && [ "$minutes" -lt $((12 * 60 + 10)) ] ;;
    4) [ "$minutes" -ge $((22 * 60 + 30)) ] && [ "$minutes" -lt $((22 * 60 + 40)) ] ;;
    5) [ "$minutes" -ge $((22 * 60)) ] && [ "$minutes" -lt $((22 * 60 + 10)) ] ;;
    *) return 1 ;;
  esac
}

while true; do
  # At most one session per day: the three windows are on different days
  marker="$STATE_DIR/$(date +%F).started"
  if is_session_window && [ ! -e "$marker" ]; then
    date '+%F %T' > "$marker"
    echo "[scheduler] starting session at $(date '+%F %T')"
    "$PROJECT_DIR/run.sh"
    echo "[scheduler] session finished with exit code $?"
  fi
  sleep 30
done
