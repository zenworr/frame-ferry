# Security

Frame Ferry's local helper runs with your user permissions. Install it only from sources you trust. The extension sends fixed playback requests, not shell commands or arbitrary mpv arguments.

Report vulnerabilities through GitHub's private reporting feature if available. Otherwise ask the maintainer for a private contact before sharing details publicly.

Do not post browser profiles, cookies, passwords, private keys, or unreviewed logs. Playback logs can contain signed media URLs and account-related errors. Keep the local configuration file private if the proxy URL includes credentials. Frame Ferry passes that URL to yt-dlp in the process environment, not as a command-line argument.
