#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
source "$repo_dir/scripts/lib/install.sh"
require_commands curl python3 cmp

commit=7785c1477103f2fafabfd65fdcf28ef26e6d7f0d
base_url="https://raw.githubusercontent.com/po5/mpv_sponsorblock/$commit"
target="$mpv_config/scripts"
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
files=(sponsorblock.lua sponsorblock_shared/main.lua sponsorblock_shared/sponsorblock.py sponsorblock_shared/LICENSE)

# Download the complete bundle before replacing any live files.
for file in "${files[@]}"; do
  remote=$file
  [[ "$file" != sponsorblock_shared/LICENSE ]] || remote=LICENSE
  download "$base_url/$remote" "$work/$file"
done
for file in "${files[@]}"; do
  install_file "$work/$file" "$target/$file"
done
printf 'Installed po5/mpv_sponsorblock at commit %s\n' "$commit"
