#!/usr/bin/env bash
set -euo pipefail

resolve_script_dir() {
  local source="$1"
  local dir
  while [ -h "$source" ]; do
    dir="$(cd -P "$(dirname "$source")" && pwd)"
    source="$(readlink "$source")"
    case "$source" in
      /*) ;;
      *) source="$dir/$source" ;;
    esac
  done
  cd -P "$(dirname "$source")" && pwd
}

SCRIPT_DIR="$(resolve_script_dir "$0")"
# shellcheck source=lib/geminiddy-lib.sh
. "$SCRIPT_DIR/lib/geminiddy-lib.sh"

usage() {
  cat <<EOF
Usage: set-geminiddy-state.sh <working|chilling|alerting> [--config <path>] [--stop-after]

Switches the Divoom display device to a preloaded Geminiddy custom face.
EOF
}

case "${1:-}" in
  -h|--help)
    usage
    exit 0
    ;;
esac

state="${1:-}"
if [ -z "$state" ]; then
  usage >&2
  exit 64
fi
shift

config="$GEMINIDDY_CONFIG_DEFAULT"
stop_after=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --config)
      config="${2:-}"
      shift 2
      ;;
    --stop-after)
      stop_after=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 64
      ;;
  esac
done

case "$state" in
  working|chilling|alerting) ;;
  *)
    geminiddy_die "unknown state '$state'. Expected: working, chilling, alerting."
    ;;
esac

geminiddy_require_macos
geminiddy_ensure_dv_app
geminiddy_load_config "$config"

started=0
if ! geminiddy_daemon_running; then
  started=1
  geminiddy_note "Bluetooth helper is not running; starting it for device at $GEMINIDDY_MINITOO_MAC..."
  geminiddy_start_daemon "$GEMINIDDY_MINITOO_MAC" || exit 1
fi

clock_id="$(geminiddy_state_clock_id "$state")"
geminiddy_send_json "$(geminiddy_selector_json "$clock_id" "$GEMINIDDY_DEVICE_ID")"
printf 'geminiddy state: %s (ClockId=%s)\n' "$state" "$clock_id"

if [ "$stop_after" -eq 1 ]; then
  geminiddy_stop_daemon
elif [ "$started" -eq 1 ]; then
  geminiddy_note "Bluetooth helper left running for faster future switches. Stop it with: $(geminiddy_dv) stop"
fi
 $(geminiddy_dv) stop"
fi
