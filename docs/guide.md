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

For eligible recorded YouTube streams, [`http_chunk_size`](../README.md#frame-ferry-configuration) sets the HTTP range request size to 1 MiB by default. Frame Ferry sets it on mpv's curl backend when enabled (mpv 0.42+). Otherwise it sets it on mpv's FFmpeg transport (`lavf`) with FFmpeg 9 or later. Explicit mpv transport settings take priority; Frame Ferry also keeps limits set by mpv from provider data. Set `0` to let mpv handle request sizes.

## Timeouts, logs, and proxy

`startup_timeout` limits the native helper, not the browser. A value above about five minutes can exceed the browser's limit for a single native messaging request. Keep the default unless you need more time for startup.

`log_retention` is a target, not a hard limit. At startup, Frame Ferry removes excess old logs but keeps recent logs that could belong to a handoff still in progress. A later launch can remove those logs when they are old enough.

An empty `proxy` uses a direct connection. A configured HTTP proxy applies to extraction and media playback. Frame Ferry ignores inherited proxy variables, including `no_proxy`. HTTPS video needs an HTTP proxy that supports CONNECT. HTTPS and SOCKS proxy URLs are not supported. Frame Ferry passes configured credentials to yt-dlp in its environment, not on its command line.

## Position and quality

Continue reads the main-page video's position. It does not read positions from child frames. If no position is available, playback uses the URL or saved history. Start from the beginning requests zero. Live/DVR positions do not transfer reliably: the browser can report a position in its DVR window that does not match the timeline in mpv.

By default, Frame Ferry pauses accessible videos at handoff start and then reads the main video's position. It does not pause frames that cannot verify the original page. If startup fails, Frame Ferry tries to resume only videos it paused on the original page with unchanged media sources. If the panel cannot confirm that playback resumed, check the tab. Turn off browser pausing to keep watching during startup; mpv can then start behind the browser position.

The **Continue in browser** control opens the YouTube URL with the current or last known position, if available. mpv closes if the browser-open command succeeds. If the command fails, mpv stays open and shows an error. If you use the control during startup, the panel reports the request, not its success, and does not resume the source videos.

If the panel reports an interrupted handoff, check both the browser and mpv. The panel will not start another automatic handoff until you make a manual request.

For YouTube, a handoff timestamp overrides saved history. Retry keeps the current position. When mpv saves the position on exit, each distinct URL can create a file in `watch_later` in Frame Ferry's player directory. Fractional timestamps can therefore create several entries for one video. Frame Ferry keeps these files as user history. `log_retention` does not remove them.

Changing the saved default resolution also updates the current panel's resolution unless you have selected a different per-launch limit.

The resolution setting is a ceiling. The player badge shows the actual stream dimensions. YouTube recovery tries additional access methods before reducing quality:

```text
Selected quality → additional access methods → earlier usable stream
                                             → fallback up to 1080p
                                             → error screen
```

Recovery has a 30-second default limit and reserves 7 seconds for the fresh fallback. A replay of an earlier usable stream has a short time limit and is skipped if it would use the fallback reserve. Changing [`recovery_timeout`](../README.md#frame-ferry-configuration) scales the route budgets and reserve. Recovery skips the signed-in route if browser cookies are not configured or the first route already used them. Account access and token support require setup below. Provider restrictions can still prevent playback.

During recorded YouTube playback, recovery starts after `stall_timeout` (10 seconds by default) of continuous buffering. It also starts if the video stream does not advance for that long while the audio position keeps advancing ahead of it. A fixed difference between audio and video positions does not trigger recovery on its own. Pausing, seeking, or resumed playback cancels the timer. Recovery keeps your position and tries the remaining access methods before lowering quality. If the fallback also stalls, recovery stops at the error screen. Use `Alt+q` to select the fast fallback early.

Timeline previews do not pass browser cookies or extractor headers to the preview player. Frame Ferry selects a low-resolution video only if it does not need special request headers or cookies. If no suitable stream is available, the preview player tries the active stream. Some streams may play without previews.

## Account access and updates

Both are off by default. Edit `script-opts/youtube.conf` in Frame Ferry's player directory:

```ini
cookies_browser=chromium:/absolute/path/to/browser-profile
cookies_initial=no
auto_update=no
```

A nonempty `cookies_browser` allows signed-in recovery through yt-dlp. Use `cookies_initial=yes` to use it on the first attempt too. The extension itself never reads cookies.

`auto_update=yes` permits one background yt-dlp update attempt per `update_interval_hours` (24 hours by default). Use it only for a yt-dlp installation you manage yourself, not a system-managed package.

For optional token-assisted recovery, install Git, Node.js 22+, and npm, then run:

```sh
./scripts/install-mpv-token-provider.sh
```

The provider runs on demand, with no persistent server. It is installed under `~/.local/share/frameferry/bgutil`, or the corresponding XDG data path. Tokens do not guarantee provider access.

## Troubleshooting

- **Native host missing:** install for the correct browser/data root, reload the extension, and use **Check native host** in the popup.
- **Missing player tools:** set absolute executable paths in [Frame Ferry configuration](../README.md#frame-ferry-configuration), or put the tools on the browser's `PATH` or in `~/.local/bin`.
- **Playback fails:** the error message identifies the player log. Check current yt-dlp support and account requirements. Browser playback does not prove extraction will work.
- **Shortcut does nothing:** configure it on the browser's extension-shortcuts page.

Run `python3 scripts/doctor --browser helium`, with your browser selected, to check installed files and versions. It compares the installed thumbfast checksum with the expected patched file. If they do not match, rerun `scripts/install-mpv-ui.sh`. It also checks the managed recovery scripts and that the required uosc and SponsorBlock files are present and nonempty. It does not test provider access or GPU output. Review logs for signed URLs and sensitive data before sharing them.

## Remove or restore

Run `./scripts/install.sh --uninstall`, then remove Frame Ferry from the browser. Uninstall keeps user edits. When it restores an original file, it prepares a copy of the backup before it replaces the managed file. If a backup is missing or the restore fails, correct the reported problem and run uninstall again. Do not remove the installation records or backups before the restore succeeds.

Downloaded components, logs, history, screenshots, and backups are retained. To remove them, first save anything you want to keep, then delete Frame Ferry's own config/data/state directories listed above. Do not delete the normal mpv directory.

Core backups are indexed by `~/.local/state/frameferry/installation.json`. UI backups are under `~/.local/state/frameferry/ui-backups`; component installers also create adjacent `.backup.<timestamp>` files. Stop players before restoring a backup. If a component installation is interrupted, rerun its installer.
