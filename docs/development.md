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
Browser action → select video → pause if enabled → capture position → native host → mpv
                   Playing or browser return requested ← keep the source videos paused
                          Startup failure ← try to resume the same videos on the same page
```

The extension is plain Manifest V3 JavaScript with no runtime npm dependencies or build step. Python runtime code uses only the standard library. Development dependencies stay outside the installed extension and native host.

The native host accepts a fixed schema: URL, position, resolution limit, and fullscreen. It does not accept shell commands or arbitrary mpv arguments. It uses mpv IPC to check for playback. A per-launch marker records a request to return to the browser, even if mpv exits before the next IPC check. The reply reports the request, not the result of the browser-open command.

When pausing is enabled, the extension selects, pauses, and reads the main video in one operation. A failed handoff triggers a resume attempt only for media that the extension paused and that did not change. The result does not wait indefinitely for browser playback to resume. After a worker restart, the extension reports an interrupted handoff instead of repeating the pending request or resuming its videos.

YouTube recovery state is separate for each player. Retained metadata uses an unlinked file descriptor. Worker cleanup and descriptor access require Linux. Account access and background updates are local opt-ins.

## Setup

Headless checks need Make, Python 3.10+, Node.js 22.13+ or 24+, npm, Lua/luac 5.4+, Luacheck 1.2+, Bash, curl, patch, diffutils, and coreutils. For Arch Linux:

```sh
sudo pacman -S --needed make python nodejs npm lua luacheck bash curl patch diffutils
make dev-setup
```

Real player checks also need mpv 0.41+, FFmpeg, and OpenSSL. `make check` does not need these tools.

`make dev-setup` installs pinned Python tools in `.venv` and npm tools in `node_modules`. Python hashes and the npm lock file are checked. npm install scripts are disabled. No system Python packages are changed.

## Required checks

```sh
make check         # headless checks; no real mpv
make test-player   # real mpv and native handoff checks
make test-slow     # real mpv recovery deadline only
make audit         # Python 3.11+ development environment only
```

- `make check` runs Ruff, ESLint, ShellCheck, Luacheck, formatting checks, syntax checks, dependency checks, and offline tests. It does not run real mpv tests. Missing headless tools, lint warnings, stale dependency pins, and test failures stop the check.
- `make test-player` runs the real playback, native handoff, and proxy tests. `make test-slow` runs only the full recovery deadline test. These targets need mpv 0.41+, FFmpeg, and OpenSSL.
- `make test-ui` runs the right-click and thumbnail tests with the pinned uosc and thumbfast components. Install the UI in scratch directories as shown below.
- `make audit` contacts Python and npm advisory services for the locked development dependencies. Python 3.10 can run the headless checks but does not install `pip-audit`. Run `make dev-setup` in a Python 3.11 or later development environment before you run the audit. Any reported vulnerability fails the check.
- `make format` applies the project formatters and safe lint fixes. Review the diff before committing.

To test the pinned UI without changing your player configuration:

```sh
scratch=$(mktemp -d)
MPV_CONFIG_DIR="$scratch/mpv" XDG_STATE_HOME="$scratch/state" scripts/install-mpv-ui.sh
FRAME_FERRY_UI_CONFIG="$scratch/mpv" make test-ui
```

CI runs `make check` and `make test-player` on Python 3.10 and 3.14. It runs `make test-slow`, `make test-ui`, and `make audit` on 3.14. Pull requests also receive a dependency review. GitHub Actions use commit pins; Dependabot checks for updates each week.

Automated tests use loopback media and simulated providers, not YouTube. Extension tests use mocks, not a desktop browser. A split-stream fixture cuts video while audio continues and checks recovery and position. The suite also covers configuration bounds, installation safety, browser navigation, authentication opt-in, worker cleanup, and false recovery. GPU output is not measured.

Run one Python test module with `python3 -m unittest tests.test_config -v`.

## Dependency changes

Keep exact development versions in `package.json` and `requirements-dev.in`. Refresh their lock files, then run all checks:

```sh
npm install --ignore-scripts
uv pip compile requirements-dev.in --universal --python-version 3.10 --generate-hashes -o requirements-dev.txt
make dev-setup
```

The lock refresh uses [uv](https://docs.astral.sh/uv/). It is not required to run Frame Ferry. For player components, update the source pins and checksums in their installers and keep [third-party notices](../THIRD_PARTY.md) current. If you change the thumbfast pin, refresh the offline source fixture. If you change the pin or patch, refresh `patches/thumbfast-low-resolution.sha256`.

Name policy values and units. Put user-facing controls in the validated runtime configuration. Keep protocol limits and internal timing constants out of the browser request schema. Numeric test fixtures are exempt from magic-number lint rules.

## Browser checks

Use the normal popup with a recorded video. Local HTTP fixtures must support byte ranges.

- Continue from a known position; compare mpv's start position.
- Start from zero despite saved history.
- Change default and per-launch resolutions separately.
- Confirm pausing before startup, resuming only previously playing videos on failure, and no pause when disabled. Check that a slow resume in a background tab does not lock the panel.
- Navigate or change the video source during startup. Frame Ferry must not resume the new video.
- Reopen the popup during a handoff and check the status and disabled buttons. After a worker restart with an unknown result, check that the panel allows a manual request but does not start one automatically.
- Request a return to the browser during mpv startup. The panel must report the request and leave the source video paused.
- Check restricted pages, unavailable positions, and embedded videos.

Run provider and GPU tests separately. Report startup time, seeking, buffering, and dropped frames separately. Redact private data from logs.

## References

- [Chromium native messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging)
- [mpv manual](https://mpv.io/manual/stable/)
- [yt-dlp documentation](https://github.com/yt-dlp/yt-dlp)
