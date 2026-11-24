# Contributing

Keep changes small and add regression tests. Run `make check` for headless checks on Python 3.10 or later. Run `make test-player` for playback, `make test-slow` for the recovery deadline, and `make test-ui` with `FRAME_FERRY_UI_CONFIG` for the pinned player UI. Run `make audit` in a Python 3.11 or later development environment; CI audits on Python 3.14. See [development](docs/development.md) for setup and browser checks.

Lint and formatting checks must pass without warnings. Name policy values, validate user settings, and update lock files when changing dependencies.

Bug reports should include tool versions, expected and actual behavior, and a reproducible example. Remove sensitive data from logs before sharing them. Report security issues as described in [SECURITY.md](SECURITY.md).

Preserve user settings, playback position, and bounded recovery. When browser pausing is enabled, pause at handoff start. On startup failure, resume only videos that Frame Ferry paused and whose media source and page did not change. Keep command execution out of the extension protocol.

Project code uses MIT; the thumbfast patch uses MPL-2.0. Preserve third-party notices and update pinned sources when changing a component.
