#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
source "$repo_dir/scripts/lib/install.sh"
require_commands git deno

# Keep the provider out of standalone yt-dlp's plugin directories.
commit=37169ee2656e08c5c2e5dc9df4c598c0cb4c88a8
base="${XDG_DATA_HOME:-$HOME/.local/share}/frameferry"
target="$base/bgutil"
mkdir -p "$base"
cache="${XDG_CACHE_HOME:-$HOME/.cache}/bgutil-ytdlp-pot-provider"
mkdir -p "$cache"
chmod 700 "$cache"
if [[ -f "$target/server/build/generate_once.js" && -d "$target/server/node_modules" ]] &&
    [[ $(git -C "$target" rev-parse HEAD 2>/dev/null) == "$commit" ]]; then
    printf 'bgutil 2.0.0 is already installed.\n'
    exit 0
fi
require_commands npm node
node -e 'if (Number(process.versions.node.split(".")[0]) < 22) { console.error("Node.js 22 or newer is required"); process.exit(1); }'
work=$(mktemp -d "$base/provider.XXXXXX")
trap 'rm -rf -- "$work"' EXIT
git clone --quiet --depth 1 --branch 2.0.0 \
    https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git "$work/bgutil"
[[ $(git -C "$work/bgutil" rev-parse HEAD) == "$commit" ]]
(
    cd "$work/bgutil/server"
    npm ci --no-audit --no-fund
    ./node_modules/.bin/tsc
)
if [[ -e "$target" ]]; then
    mv -- "$target" "$base/bgutil.backup.$timestamp"
fi
mv -- "$work/bgutil" "$target"
printf 'Installed bgutil 2.0.0 for on-demand mpv token generation. No server is started.\n'
