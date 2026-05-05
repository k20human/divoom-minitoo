#!/usr/bin/env bash

geminiddy_resolve_path() {
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

GEMINIDDY_LIB_DIR="$(geminiddy_resolve_path "${BASH_SOURCE[0]}")"
GEMINIDDY_PACKAGE_DIR="$(cd "$GEMINIDDY_LIB_DIR/.." && pwd)"
GEMINIDDY_REPO_ROOT="$(cd "$GEMINIDDY_PACKAGE_DIR/../.." && pwd)"
GEMINIDDY_CORE_DIR_DEFAULT="$GEMINIDDY_REPO_ROOT/core"
GEMINIDDY_CONFIG_DEFAULT="${GEMINIDDY_CONFIG:-$HOME/.geminiddy/config}"
GEMINIDDY_DETECTED_DEFAULT="${GEMINIDDY_DETECTED:-$HOME/.geminiddy/detected}"
GEMINIDDY_FIFO="${DIVOOM_FIFO:-/tmp/divoom.fifo}"
GEMINIDDY_LOG="${DIVOOM_LOG:-/tmp/divoom-send.log}"

geminiddy_die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

geminiddy_note() {
  printf '%s\n' "$*" >&2
}

geminiddy_normalize_mac() {
  printf '%s\n' "${1//-/:}" | tr '[:lower:]' '[:upper:]'
}

geminiddy_is_mac() {
  [[ "$1" =~ ^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$ ]]
}

geminiddy_is_device_id() {
  [[ "$1" =~ ^[0-9]+$ ]]
}

geminiddy_config_get() {
  local config="$1"
  local key="$2"
  [ -f "$config" ] || return 1
  (
    set +u
    # shellcheck source=/dev/null
    . "$config" >/dev/null 2>&1 || exit 1
    case "$key" in
      GEMINIDDY_MINITOO_MAC) printf '%s\n' "${GEMINIDDY_MINITOO_MAC:-}" ;;
      GEMINIDDY_DEVICE_ID) printf '%s\n' "${GEMINIDDY_DEVICE_ID:-}" ;;
      *) exit 1 ;;
    esac
  )
}

geminiddy_write_detected_config() {
  local config="$1"
  local mac="$2"
  local device_id="$3"

  mkdir -p "$(dirname "$config")" || return 1
  {
    printf '# Geminiddy Bluetooth detection cache.\n'
    printf '# Contains no Divoom password, auth token, or account secret.\n'
    [ -n "$mac" ] && printf 'GEMINIDDY_MINITOO_MAC=%q\n' "$mac"
    [ -n "$device_id" ] && printf 'GEMINIDDY_DEVICE_ID=%q\n' "$device_id"
  } > "$config"
  chmod 600 "$config"
}

geminiddy_detect_minitoo_macs() {
  python3 "$GEMINIDDY_PACKAGE_DIR/tools/detect-minitoo-mac.py"
}

geminiddy_require_macos() {
  local os
  os="$(uname -s)"
  if [ "$os" != "Darwin" ] && [ "$os" != "Linux" ] && [[ "$os" != MINGW* ]] && [[ "$os" != CYGWIN* ]] && [[ "$os" != MSYS* ]]; then
    geminiddy_die "Geminiddy currently supports macOS, Linux and Windows only."
  fi
}

geminiddy_require_python_pillow() {
  command -v python3 >/dev/null 2>&1 || geminiddy_die "python3 is required."
  if ! python3 - <<'PY' >/dev/null 2>&1
from PIL import Image
PY
  then
    geminiddy_die "Python Pillow is required. Install it with: python3 -m pip install Pillow"
  fi
}

geminiddy_core_dir() {
  printf '%s\n' "${GEMINIDDY_CORE_DIR:-$GEMINIDDY_CORE_DIR_DEFAULT}"
}

geminiddy_dv() {
  printf '%s/dv\n' "$(geminiddy_core_dir)"
}

geminiddy_require_dv() {
  local dv
  dv="$(geminiddy_dv)"
  [ -x "$dv" ] || geminiddy_die "missing Divoom Bluetooth helper: $dv"
}

geminiddy_ensure_dv_app() {
  local dir
  dir="$(geminiddy_core_dir)"
  geminiddy_require_dv
  if [ "$(uname -s)" = "Darwin" ]; then
    if [ ! -x "$dir/divoom-send.app/Contents/MacOS/divoom-send" ]; then
      geminiddy_note "Building macOS Bluetooth helper..."
      (cd "$dir" && ./build.sh) || geminiddy_die "failed to build divoom-send.app. Xcode command line tools may be missing."
    fi
  fi
}

geminiddy_daemon_running() {
  [ -p "$GEMINIDDY_FIFO" ] && (pgrep -f "divoom-send" || pgrep -f "divoom-send-linux.py") >/dev/null 2>&1
}

geminiddy_clear_stale_fifo() {
  if [ -p "$GEMINIDDY_FIFO" ] && ! (pgrep -f "divoom-send" || pgrep -f "divoom-send-linux.py") >/dev/null 2>&1; then
    rm -f "$GEMINIDDY_FIFO"
  fi
}

geminiddy_bluetooth_help() {
  cat >&2 <<EOF
Could not connect to the Divoom display device over Bluetooth.

Check:
  1. Device is powered on and awake.
  2. It is paired in Bluetooth settings.
  3. The Divoom phone app is not currently connected to the device.
  4. The Bluetooth MAC address in the Geminiddy config is correct.

Recent helper log:
EOF
  tail -n 40 "$GEMINIDDY_LOG" >&2 2>/dev/null || true
}

geminiddy_start_daemon() {
  local mac="$1"
  local dv
  dv="$(geminiddy_dv)"
  geminiddy_clear_stale_fifo
  if geminiddy_daemon_running; then
    return 0
  fi
  if ! "$dv" start "$mac" >/tmp/geminiddy-dv-start.out 2>&1; then
    cat /tmp/geminiddy-dv-start.out >&2 2>/dev/null || true
    geminiddy_bluetooth_help
    return 1
  fi
}

geminiddy_stop_daemon() {
  local dv
  dv="$(geminiddy_dv)"
  "$dv" stop >/dev/null 2>&1 || true
}

geminiddy_check_connection() {
  local mac="$1"
  local dv detected
  dv="$(geminiddy_dv)"

  geminiddy_stop_daemon
  if ! geminiddy_start_daemon "$mac"; then
    return 1
  fi
  "$dv" raw bd 2b 00 >/dev/null 2>&1 || true
  sleep 1
  detected="$(python3 "$GEMINIDDY_PACKAGE_DIR/tools/parse-device-id-log.py" "$GEMINIDDY_LOG" 2>/dev/null || true)"
  geminiddy_stop_daemon
  printf '%s\n' "$detected"
}

geminiddy_load_config() {
  local config="$1"
  [ -f "$config" ] || geminiddy_die "missing config: $config. Run install.sh first."
  # shellcheck source=/dev/null
  . "$config"
  : "${GEMINIDDY_MINITOO_MAC:?missing GEMINIDDY_MINITOO_MAC in config}"
  : "${GEMINIDDY_DEVICE_ID:?missing GEMINIDDY_DEVICE_ID in config}"
  : "${GEMINIDDY_CLOCK_CHILLING:?missing GEMINIDDY_CLOCK_CHILLING in config}"
  : "${GEMINIDDY_CLOCK_WORKING:?missing GEMINIDDY_CLOCK_WORKING in config}"
  : "${GEMINIDDY_CLOCK_ALERTING:?missing GEMINIDDY_CLOCK_ALERTING in config}"
}

geminiddy_state_clock_id() {
  case "$1" in
    chilling) printf '%s\n' "$GEMINIDDY_CLOCK_CHILLING" ;;
    working) printf '%s\n' "$GEMINIDDY_CLOCK_WORKING" ;;
    alerting) printf '%s\n' "$GEMINIDDY_CLOCK_ALERTING" ;;
    *) return 1 ;;
  esac
}

geminiddy_state_page_index() {
  case "$1" in
    chilling) printf '%s\n' "${GEMINIDDY_PAGE_CHILLING:-0}" ;;
    working) printf '%s\n' "${GEMINIDDY_PAGE_WORKING:-1}" ;;
    alerting) printf '%s\n' "${GEMINIDDY_PAGE_ALERTING:-2}" ;;
    *) return 1 ;;
  esac
}

geminiddy_state_style_id() {
  case "$1" in
    chilling) printf '%s\n' "${GEMINIDDY_STYLE_CHILLING:-798}" ;;
    working) printf '%s\n' "${GEMINIDDY_STYLE_WORKING:-828}" ;;
    alerting) printf '%s\n' "${GEMINIDDY_STYLE_ALERTING:-798}" ;;
    *) return 1 ;;
  esac
}

geminiddy_selector_json() {
  local clock_id="$1"
  local device_id="$2"
  printf '{"Command":"Channel/SetClockSelectId","ClockId":%s,"DeviceId":%s,"ParentClockId":0,"ParentItemId":"","PageIndex":0,"LcdIndependence":0,"LcdIndex":0,"Language":"en"}' "$clock_id" "$device_id"
}

geminiddy_clean_json() {
  local page_index="$1"
  local clock_id="$2"
  local device_id="$3"
  printf '{"Command":"Channel/CleanCustom","CustomPageIndex":%s,"ClockId":%s,"ParentClockId":0,"ParentItemId":"","DeviceId":%s}' "$page_index" "$clock_id" "$device_id"
}

geminiddy_set_custom_json() {
  local page_index="$1"
  local file_id="$2"
  local clock_id="$3"
  local device_id="$4"
  printf '{"Command":"Channel/SetCustom","CustomPageIndex":%s,"CustomId":0,"FileId":"%s","ClockId":%s,"ParentClockId":0,"ParentItemId":"","LcdIndependence":0,"LcdIndex":0,"Language":"en","DeviceId":%s}' "$page_index" "$file_id" "$clock_id" "$device_id"
}

geminiddy_style_json() {
  local clock_id="$1"
  local style_id="$2"
  local device_id="$3"
  printf '{"Command":"Channel/SetClockStyle","ClockId":%s,"StyleId":%s,"DeviceId":%s,"ParentClockId":0,"ParentItemId":"","PageIndex":0,"LcdIndependence":0,"LcdIndex":0,"Language":"en"}' "$clock_id" "$style_id" "$device_id"
}

geminiddy_send_json() {
  local json="$1"
  local dv
  dv="$(geminiddy_dv)"
  if ! geminiddy_daemon_running; then
    geminiddy_die "Bluetooth helper is not running."
  fi
  "$dv" json "$json" || geminiddy_die "failed to send Bluetooth JSON command."
}

geminiddy_wait_for_upload_ack() {
  local timeout="${1:-30}"
  local deadline=$((SECONDS + timeout))
  while [ "$SECONDS" -lt "$deadline" ]; do
    if grep -q "bd 55 13 01 05 00" "$GEMINIDDY_LOG" 2>/dev/null; then
      return 0
    fi
    sleep 0.2
  done
  return 1
}

geminiddy_start_custom_daemon() {
  local mac="$1"
  local file_id="$2"
  local rawfile="$3"
  local device_id="$4"
  local delay_ms="$5"
  local dv
  dv="$(geminiddy_dv)"

  geminiddy_stop_daemon
  geminiddy_clear_stale_fifo
  if ! "$dv" start-custom "$mac" "$file_id" "$rawfile" "$device_id" "$delay_ms" >/tmp/geminiddy-dv-start-custom.out 2>&1; then
    cat /tmp/geminiddy-dv-start-custom.out >&2 2>/dev/null || true
    geminiddy_bluetooth_help
    return 1
  fi
}

geminiddy_upload_custom() {
  local state="$1"
  local mac="$2"
  local file_id="$3"
  local rawfile="$4"
  local page_index="$5"
  local clock_id="$6"
  local style_id="$7"
  local device_id="$8"
  local delay_ms="${9:-5}"

  geminiddy_note "Uploading $state to CustomPageIndex=$page_index ClockId=$clock_id..."
  geminiddy_start_custom_daemon "$mac" "$file_id" "$rawfile" "$device_id" "$delay_ms" || return 1
  # The MiniToo upload handshake is tied to the custom page index. In live
  # tests it requested file chunks when CleanCustom/SetCustom used ClockId=0;
  # the real custom ClockId is still used below for style and runtime selection.
  geminiddy_send_json "$(geminiddy_clean_json "$page_index" 0 "$device_id")"
  geminiddy_send_json "$(geminiddy_set_custom_json "$page_index" "$file_id" 0 "$device_id")"
  if ! geminiddy_wait_for_upload_ack 45; then
    geminiddy_bluetooth_help
    geminiddy_stop_daemon
    geminiddy_die "timed out waiting for device to ACK $state upload."
  fi
  geminiddy_send_json "$(geminiddy_style_json "$clock_id" "$style_id" "$device_id")"
  geminiddy_stop_daemon
}
 "$clock_id" "$style_id" "$device_id")"
  geminiddy_stop_daemon
}
