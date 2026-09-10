#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -euo pipefail
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
exec python3 "$repo_dir/scripts/setup-frameferry" "$@"
