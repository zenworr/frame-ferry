# Contributing

Keep changes small and add regression tests. Run `make check`, `make test-player`, `make test-slow`, and `make audit`; see [development](docs/development.md) for setup and browser checks. Lint and formatting checks must pass without warnings. Name policy values, validate user settings, and update lock files when changing dependencies.

Bug reports should include tool versions, expected and actual behavior, and a reproducible example. Remove sensitive data from logs before sharing them. Report security issues as described in [SECURITY.md](SECURITY.md).

Preserve user settings, playback position, and bounded recovery. When browser pausing is enabled, pause at handoff start. On startup failure, resume only the videos Frame Ferry paused and still owns. Keep command execution out of the extension protocol.

Project code uses MIT; the thumbfast patch uses MPL-2.0. Preserve third-party notices and update pinned sources when changing a component.
