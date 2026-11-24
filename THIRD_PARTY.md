# Third-party components

Frame Ferry code and artwork use the [MIT license](LICENSE). The [thumbfast patch](patches/thumbfast-low-resolution.patch) uses [MPL-2.0](LICENSES/MPL-2.0.txt); modified thumbfast source retains its upstream notices.

## Installed by the setup scripts

The setup scripts download these components at pinned versions.

| Component | Purpose | License |
| --- | --- | --- |
| [uosc](https://github.com/tomasklaen/uosc) | Player controls and menus | MIT; bundled [Material Icons](https://github.com/google/material-design-icons) use Apache-2.0 |
| [thumbfast](https://github.com/po5/thumbfast) | Timeline previews | MPL-2.0 |
| [mpv_sponsorblock](https://github.com/po5/mpv_sponsorblock) | SponsorBlock chapters | GPL-3.0 |
| [bgutil-ytdlp-pot-provider](https://github.com/Brainicism/bgutil-ytdlp-pot-provider) | Optional YouTube access recovery | GPL-3.0; npm dependencies have their own licenses |

Keep upstream license notices when redistributing these components. Frame Ferry's MIT license does not replace their licenses.

## Test fixture

[tests/fixtures/thumbfast.lua.gz](tests/fixtures/thumbfast.lua.gz) contains upstream `thumbfast.lua` from commit [`0f711de3138c9bd6718209d819ac54022c23ded2`](https://github.com/po5/thumbfast/commit/0f711de3138c9bd6718209d819ac54022c23ded2). It retains the upstream [MPL-2.0](LICENSES/MPL-2.0.txt) notice. The fixture lets tests verify the patch without network access. It is not installed.
