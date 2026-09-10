# Contributing

Keep changes small and add regression tests. Run `make check` and `make test-slow`; see [development](docs/development.md) for dependencies and browser checks.

Bug reports should include tool versions, expected and actual behavior, and a reproducible example. Remove sensitive data from logs before sharing them. Report security issues as described in [SECURITY.md](SECURITY.md).

Preserve user settings, playback position, bounded recovery, and pause-after-success behavior. Keep command execution out of the extension protocol.

Project code uses MIT; the thumbfast patch uses MPL-2.0. Preserve third-party notices and update pinned sources when changing a component.
