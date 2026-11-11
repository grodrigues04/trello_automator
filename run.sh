#!/usr/bin/env bash
# Runs one session. Called by scheduler.sh in the container, or by hand on the host (where node
# comes from nvm and claude, gh and uv from ~/.local/bin).
set -euo pipefail

export NVM_DIR="$HOME/.nvm"
# shellcheck source=/dev/null
[ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"
export PATH="$HOME/.local/bin:$PATH"

cd "$(dirname "$0")"
exec uv run --frozen trello-automator "$@"
