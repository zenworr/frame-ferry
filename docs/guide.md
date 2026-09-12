# User guide

See the [README](../README.md) for installation and playback controls.

## Browser setup

The installer has registration paths for Helium, Chromium, Chrome, and Brave. Helium's AppImage has been tested. To use a custom browser data directory:

```sh
./scripts/install.sh --browser-data-dir /absolute/path/to/browser-data
python3 scripts/doctor --browser-data-dir /absolute/path/to/browser-data
```

Use the browser's **user-data root**, not its `Default` profile subdirectory. This registers the native host; it does not enable account access.

Flatpak/Snap browsers need integration that can launch the helper outside their sandbox. This installer does not configure or test that path. “Native messaging” names the browser API; it does not require a system-packaged browser.

## Browser settings

Enable **Continue in mpv when opening the panel** under **Defaults & settings** to start the handoff when you click the extension icon. The panel stays open and shows the result. This setting is off by default and also applies when the keyboard shortcut opens the panel. It requests the current position regardless of the separate default playback action.

## Player settings and files

Default locations follow `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, and `XDG_STATE_HOME`:

| Default path | Contents |
| --- | --- |
| `~/.config/frameferry/mpv` | Player configuration, watch history, screenshots |
| `~/.local/share/frameferry` | Native host, wrapper, extension |
| `~/.local/state/frameferry` | Installation records, backups, playback logs |

Frame Ferry uses its own mpv configuration. Normal `mpv URL` commands still use your normal settings.

Software decoding is the default. If playback drops frames, use `Ctrl+h` to compare hardware decoding. HDR output depends on your driver, display, and compositor.

## Position and quality

Continue reads the main-page video's position when clicked. It does not read positions from child frames or support live/DVR position transfer. If no position is available, playback uses the URL or saved history. Start from the beginning explicitly requests zero.

For YouTube, a handoff timestamp overrides saved history. Retry keeps the current position. Accessible browser videos are paused only after mpv confirms playback; frames that cannot verify the original page stay playing.

The resolution setting is a ceiling. The player badge shows the actual stream dimensions. YouTube recovery tries additional access methods before reducing quality:

```text
Selected quality → additional access methods → earlier usable stream
                                             → fallback up to 1080p
                                             → error screen
```

Recovery has a 30-second limit. Account access and token support require setup below; unavailable routes are skipped or fail quickly. Provider restrictions can still prevent playback. `Alt+q` goes directly to the fast fallback.

## Account access and updates

Both are off by default. Edit `script-opts/youtube.conf` in Frame Ferry's player directory:

```ini
cookies_browser=chromium:/absolute/path/to/browser-profile
cookies_initial=no
auto_update=no
```

A nonempty `cookies_browser` allows signed-in recovery through yt-dlp. Use `cookies_initial=yes` to use it on the first attempt too. The extension itself never reads cookies.

`auto_update=yes` permits one background yt-dlp update check per day. Use it only for a yt-dlp installation you manage yourself, not a system-managed package.

For optional token-assisted recovery, install Git, Node.js 22+, and npm, then run:

```sh
./scripts/install-mpv-token-provider.sh
```

The provider runs on demand, with no persistent server. It is installed under `~/.local/share/frameferry/bgutil`, or the corresponding XDG data path. Tokens do not guarantee provider access.

## Troubleshooting

- **Native host missing:** install for the correct browser/data root, reload the extension, and use **Check native host** in the popup.
- **Missing player tools:** ensure the browser-launched process can find them. The host also adds `~/.local/bin` to PATH.
- **Playback fails:** check current yt-dlp support and account requirements. Browser playback does not prove extraction will work.
- **Shortcut does nothing:** configure it on the browser's extension-shortcuts page.

Run `python3 scripts/doctor --browser helium`, with your browser selected, to check installed files and versions. It does not test provider access or GPU output. Review logs for signed URLs and sensitive data before sharing them.

## Remove or restore

Run `./scripts/install.sh --uninstall`, then remove Frame Ferry from the browser. Uninstall restores saved original files and keeps user edits.

Downloaded components, logs, history, screenshots, and backups are retained. To remove them, first save anything you want to keep, then delete Frame Ferry's own config/data/state directories listed above. Do not delete the normal mpv directory.

Core backups are indexed by `~/.local/state/frameferry/installation.json`. UI backups are under `~/.local/state/frameferry/ui-backups`; component installers also create adjacent `.backup.<timestamp>` files. Stop players before restoring a backup. If a component installation is interrupted, rerun its installer.
