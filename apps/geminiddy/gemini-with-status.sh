#!/usr/bin/env bash
# Wrapper for Gemini CLI to show status on a Divoom MiniToo via Geminiddy.

set -u

# Try to find geminiddy-hook.sh on PATH or in the repo.
HOOK_CMD="geminiddy-hook.sh"
if ! command -v "$HOOK_CMD" >/dev/null 2>&1; then
  # Fallback to absolute path relative to this script if possible.
  HERE="$(cd "$(dirname "$0")" && pwd)"
  if [ -x "$HERE/geminiddy-hook.sh" ]; then
    HOOK_CMD="$HERE/geminiddy-hook.sh"
  else
    # Last resort: try the default app path.
    HOOK_CMD="/home/k20/DEV/divoom-minitoo/apps/geminiddy/geminiddy-hook.sh"
  fi
fi

# Set status to working.
"$HOOK_CMD" working >/dev/null 2>&1 &

# Run gemini with all passed arguments.
# Use exec to replace the shell process.
# But wait, we need to set status back to chilling after.
# So we don't use exec here.
gemini "$@"
EXIT_CODE=$?

# Set status back to chilling.
"$HOOK_CMD" chilling >/dev/null 2>&1 &

exit $EXIT_CODE
