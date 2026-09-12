// SPDX-License-Identifier: MIT
export const defaults = Object.freeze({resume: true, pause: true, fullscreen: false, autoContinue: false, quality: 2160});
export const heights = [0, 480, 720, 1080, 1440, 2160];
export function normalize(value = {}) {
  const result = {...defaults};
  for (const key of ['resume', 'pause', 'fullscreen', 'autoContinue']) if (typeof value[key] === 'boolean') result[key] = value[key];
  if (heights.includes(value.quality)) result.quality = value.quality;
  return result;
}
export async function settings() {
  return normalize((await chrome.storage.local.get('preferences')).preferences);
}
export function sameVideo(first, second) {
  function identity(text) {
    const url = new URL(text);
    const host = url.hostname.toLowerCase();
    if (host === 'youtu.be') return 'youtube:' + url.pathname.split('/')[1];
    if (host === 'youtube.com' || host.endsWith('.youtube.com') || host.endsWith('.youtube-nocookie.com')) {
      const id = url.pathname === '/watch' ? url.searchParams.get('v') : url.pathname.match(/^\/(shorts|embed|live)\/([^/]+)/)?.[2];
      if (id) return 'youtube:' + id;
    }
    url.hash = '';
    return url.href;
  }
  try { return identity(first) === identity(second); } catch { return false; }
}
