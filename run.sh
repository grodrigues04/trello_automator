#!/usr/bin/env bash
# Entry point of the systemd timer. systemd starts without the shell profile, so node (nvm),
# claude, gh and uv are put on the PATH here.
set -euo pipefail

export NVM_DIR="$HOME/.nvm"
# shellcheck source=/dev/null
[ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"
export PATH="$HOME/.local/bin:$PATH"

cd "$(dirname "$0")"
exec uv run --frozen trello-automator "$@"
