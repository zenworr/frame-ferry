#!/usr/bin/env bash

timestamp=$(date +%Y%m%dT%H%M%S.%N)
mpv_config="${MPV_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/frameferry/mpv}"

require_commands() {
  local name
  for name in "$@"; do
    command -v "$name" >/dev/null || { printf 'Missing required command: %s\n' "$name" >&2; return 1; }
  done
}

download() {
  mkdir -p -- "$(dirname -- "$2")"
  curl -fsSL --max-time 60 --connect-timeout 10 -o "$2" -- "$1"
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
