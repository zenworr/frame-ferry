#!/usr/bin/env bash

timestamp=$(date +%Y%m%dT%H%M%S.%N)
# Component installers use this value after sourcing the library.
# shellcheck disable=SC2034
mpv_config="${MPV_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/frameferry/mpv}"

for name in MPV_CONFIG_DIR XDG_CONFIG_HOME XDG_DATA_HOME XDG_STATE_HOME XDG_CACHE_HOME; do
  if [[ -n "${!name:-}" && "${!name}" != /* ]]; then
    printf '%s must be an absolute path.\n' "$name" >&2
    return 1
  fi
done

require_commands() {
  local name
  for name in "$@"; do
    command -v "$name" >/dev/null || { printf 'Missing required command: %s\n' "$name" >&2; return 1; }
  done
}

download_timeout=60
connect_timeout=10
download() {
  mkdir -p -- "$(dirname -- "$2")"
  curl -fsSL --max-time "$download_timeout" --connect-timeout "$connect_timeout" -o "$2" -- "$1"
}

install_file() (
  local source=$1 target=$2
  trap 'rm -f -- "$target.tmp.$$"' EXIT
  if [[ -f "$target" ]] && cmp -s -- "$source" "$target"; then
    return
  fi
  mkdir -p -- "$(dirname -- "$target")"
  cp -- "$source" "$target.tmp.$$"
  if [[ -e "$target" || -L "$target" ]]; then
    mv -- "$target" "$target.backup.$timestamp"
  fi
  mv -- "$target.tmp.$$" "$target"
)
