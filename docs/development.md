# Development

## Structure

```text
extension/           Browser UI, settings, capture, and native messaging
scripts/             Native host, extractor, installation, and diagnostics
  frameferry_config.py   Shared runtime defaults, validation, and dependencies
  frameferry_install.py  Shared installation identity and atomic file writes
config/mpv/          Player settings and per-player recovery scripts
patches/             Pinned third-party changes
tests/               Offline fixtures and regression tests
```

```text
Browser action → extension → native host → mpv → yt-dlp
                            ← playback confirmation
Browser pause ← extension
```

The extension is plain Manifest V3 JavaScript with no runtime npm dependencies or build step. Python runtime code uses only the standard library. Development dependencies stay outside the installed extension and native host.

The native host accepts a fixed schema: URL, position, resolution limit, and fullscreen. It does not accept shell commands or arbitrary mpv arguments. It confirms playback through mpv IPC before the browser pauses.

YouTube recovery state is separate for each player. Retained metadata uses an unlinked file descriptor. Worker cleanup and descriptor access require Linux. Account access and background updates are local opt-ins.

## Setup

Install Make, Python 3.10+, Node.js 22.13+ or 24+, npm, Lua/luac 5.4+, Luacheck 1.2+, mpv 0.41+, FFmpeg, Bash, curl, patch, and diffutils. For Arch Linux:

```sh
sudo pacman -S --needed make python nodejs npm lua luacheck mpv ffmpeg bash curl patch diffutils
make dev-setup
```

`make dev-setup` installs pinned Python tools in `.venv` and npm tools in `node_modules`. Python hashes and the npm lock file are checked. npm install scripts are disabled. No system Python packages are changed.

## Required checks

```sh
make check
make test-slow
make audit
```

- `make check` runs Ruff, ESLint, ShellCheck, Luacheck, formatting checks, syntax checks, dependency checks, and offline tests. Missing tools, lint warnings, stale dependency pins, and test failures stop the check.
- `make test-slow` also tests the full recovery deadline with real mpv.
- `make audit` contacts Python and npm advisory services for the locked development dependencies. Any reported vulnerability fails the check. Keep this network check separate from offline tests. External player tools and optional components are installed separately; setup and doctor check the required runtime tool versions.
- `make format` applies the project formatters and safe lint fixes. Review the diff before committing.

CI checks Python 3.10 and 3.14. It runs the slow suite on 3.14 and audits both environments. Pull requests also receive a dependency review. GitHub Actions use commit pins; Dependabot checks for updates each week.

Tests use loopback media and simulated providers, not YouTube. A split-stream fixture cuts video while audio continues and checks recovery and position. The suite also covers configuration bounds, installation safety, browser navigation, authentication opt-in, worker cleanup, and false recovery. GPU output is not measured.

Run one Python test module with `python3 -m unittest tests.test_config -v`.

## Dependency changes

Keep exact development versions in `package.json` and `requirements-dev.in`. Refresh their lock files, then run all checks:

```sh
npm install --ignore-scripts
uv pip compile requirements-dev.in --universal --python-version 3.10 --generate-hashes -o requirements-dev.txt
make dev-setup
```

The lock refresh uses [uv](https://docs.astral.sh/uv/). It is not required to run Frame Ferry. For player components, update the source pins and checksums in their installers and keep [third-party notices](../THIRD_PARTY.md) current.

Name policy values and units. Put user-facing controls in the validated runtime configuration. Keep protocol limits and internal timing constants out of the browser request schema. Numeric test fixtures are exempt from magic-number lint rules.

## Browser checks

Use the normal popup with a recorded video. Local HTTP fixtures must support byte ranges.

- Continue from a known position; compare mpv's start position.
- Start from zero despite saved history.
- Change default and per-launch resolutions separately.
- Confirm pausing only after success, and no pause when disabled or startup fails.
- Navigate during startup; the new page must stay playing.
- Reopen the popup during a handoff and check the status and disabled buttons.
- Check restricted pages, unavailable positions, and embedded videos.

Run provider and GPU tests separately. Report startup time, seeking, buffering, and dropped frames separately. Redact private data from logs.

## References

- [Chromium native messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging)
- [mpv manual](https://mpv.io/manual/stable/)
- [yt-dlp documentation](https://github.com/yt-dlp/yt-dlp)
