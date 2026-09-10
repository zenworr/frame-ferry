# Development

## Design

```text
Browser action → extension → native host → mpv → yt-dlp
                            ← playback confirmation
Browser pause ← extension
```

The extension is plain Manifest V3 JavaScript, with no build step or npm dependencies. The public key in its manifest keeps its unpacked extension ID stable. `extension/icons/icon.svg` is the source artwork.

The Python host accepts a fixed, versioned message schema: URL, position, resolution limit, and fullscreen. It does not accept shell commands or arbitrary mpv arguments. It confirms playback through mpv IPC before the extension attempts to pause the browser.

YouTube recovery state is separate for each player. Retained extraction metadata uses an unlinked file descriptor; worker cleanup and this descriptor access require Linux. Account access and background updates are local opt-ins.

## Tests

Install Make, Python 3.10+, Lua/luac 5.4, Node.js 22+, mpv 0.41+, Bash, curl, patch, and diffutils.

```sh
make check
make test-slow
```

The suite covers the native protocol, extension behavior, installation and removal, extraction cleanup, recovery, and player controls. The slow suite includes the full 30-second recovery deadline. GitHub Actions runs both commands.

Tests use local media and simulated providers. They do not contact YouTube or measure GPU output. mpv and JavaScript tests are skipped if their tools are absent; install both for a complete run.

## Browser checks

Use the normal popup with a recorded video. For local fixtures, the HTTP server must support byte ranges.

- Continue from a known position and compare mpv's start position.
- Start from zero despite saved history.
- Change the per-launch resolution without changing the saved default.
- Confirm browser pausing only after success, and no pause when disabled or startup fails.
- Navigate during startup; the new page must stay playing.
- Reload the popup and check that settings persist.
- Check unavailable positions, restricted pages, and embedded videos.

Use real provider and GPU tests separately from the offline suite. Report startup time, seeking, buffering, and dropped frames separately.

## References

- [Chromium native messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging)
- [activeTab permission](https://developer.chrome.com/docs/extensions/develop/concepts/activeTab)
- [mpv manual](https://mpv.io/manual/stable/)
- [yt-dlp documentation](https://github.com/yt-dlp/yt-dlp)
