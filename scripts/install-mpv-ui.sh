#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
source "$repo_dir/scripts/lib/install.sh"
require_commands curl python3 patch cmp
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT

uosc_version=5.13.0
thumbfast_commit=0f711de3138c9bd6718209d819ac54022c23ded2
curl -fLSs --max-time 60 -o "$work/uosc.zip" \
  "https://github.com/tomasklaen/uosc/releases/download/$uosc_version/uosc.zip"
curl -fLSs --max-time 30 -o "$work/thumbfast.lua" \
  "https://raw.githubusercontent.com/po5/thumbfast/$thumbfast_commit/thumbfast.lua"

python3 - "$work" <<'PY'
import hashlib
from pathlib import Path
import sys
import zipfile

root = Path(sys.argv[1])
expected = {
    "uosc.zip": "4be9da3289285300fa374496c3f1bfd7bb20ac08e890d25bd5a06b28eebe4882",
    "thumbfast.lua": "a3d08e71eae8b892f6cd39f9593ea219768e709312d176bca883841b156448bf",
}
for name, digest in expected.items():
    if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
        raise SystemExit(f"Checksum mismatch: {name}")
with zipfile.ZipFile(root / "uosc.zip") as archive:
    for name in archive.namelist():
        if Path(name).is_absolute() or ".." in Path(name).parts:
            raise SystemExit(f"Unsafe archive path: {name}")
    archive.extractall(root / "uosc")
PY
patch --batch --fuzz=0 -s -p1 -d "$work" < "$repo_dir/patches/thumbfast-low-resolution.patch"

config="$mpv_config"
if python3 - "$work" "$config" <<'PY'
import os
from pathlib import Path
import sys
source, target = map(Path, sys.argv[1:])
files = [(source / 'thumbfast.lua', target / 'scripts/thumbfast.lua')]
for folder in ('scripts/uosc', 'fonts'):
    root = source / 'uosc' / folder
    files += [(p, target / folder / p.relative_to(root)) for p in root.rglob('*') if p.is_file()]
try:
    same = all(a.read_bytes() == b.read_bytes() for a, b in files)
    same = same and os.access(target / 'scripts/uosc/bin/ziggy-linux', os.X_OK)
except OSError:
    same = False
sys.exit(0 if same else 1)
PY
then
  printf 'uosc and thumbfast already match the pinned files.\n'
  exit 0
fi
backup="${XDG_STATE_HOME:-$HOME/.local/state}/frameferry/ui-backups/$timestamp"
mkdir -p "$config/scripts" "$config/fonts" "$backup"
for name in uosc thumbfast.lua; do
  if [[ -e "$config/scripts/$name" ]]; then
    mv -- "$config/scripts/$name" "$backup/$name"
  fi
done
cp -a "$work/uosc/scripts/uosc" "$config/scripts/uosc"
while IFS= read -r -d '' font; do
  install_file "$font" "$config/fonts/${font#"$work/uosc/fonts/"}"
done < <(find "$work/uosc/fonts" -type f -print0)
cp "$work/thumbfast.lua" "$config/scripts/thumbfast.lua"
chmod 755 "$config/scripts/uosc/bin/ziggy-linux"
printf 'Installed uosc %s and thumbfast %s with low-resolution previews.\n' "$uosc_version" "$thumbfast_commit"
printf 'Previous scripts: %s\n' "$backup"
