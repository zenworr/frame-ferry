// SPDX-License-Identifier: MIT
export const resolutions = Object.freeze({unlimited: 0, sd: 480, hd: 720, fullHd: 1080, qhd: 1440, uhd: 2160});
export const defaults = Object.freeze({
  resume: true,
  pause: true,
  fullscreen: false,
  autoContinue: false,
  quality: resolutions.uhd,
});
export const heights = Object.freeze(Object.values(resolutions));
export function normalize(value = {}) {
  const result = {...defaults};
  for (const key of ['resume', 'pause', 'fullscreen', 'autoContinue'])
    if (typeof value[key] === 'boolean') result[key] = value[key];
  if (heights.includes(value.quality)) result.quality = value.quality;
  return result;
}
export async function settings() {
  return normalize((await chrome.storage.local.get('preferences')).preferences);
}
export function isYouTubeNoCookie(host) {
  return host === 'youtube-nocookie.com' || host.endsWith('.youtube-nocookie.com');
}
export function youtubeVideoId(url) {
  const host = url.hostname;
  if (host === 'youtu.be') return url.pathname.split('/')[1] || null;
  if (host === 'youtube.com' || host.endsWith('.youtube.com') || isYouTubeNoCookie(host)) {
    return url.pathname === '/watch'
      ? url.searchParams.get('v') || null
      : (url.pathname.match(/^\/(shorts|embed|live)\/([^/]+)/)?.[2] ?? null);
  }
  return undefined;
}
export function sameVideo(first, second) {
  function identity(text) {
    const url = new URL(text);
    const id = youtubeVideoId(url);
    if (id !== undefined) return id && `youtube:${id}`;
    if (/^#t=(?:npt:)?(?:\d+:){0,2}\d+(?:\.\d+)?(?:,(?:\d+:){0,2}\d+(?:\.\d+)?)?$/.test(url.hash)) url.hash = '';
    return url.href;
  }
  try {
    const id = identity(first);
    return Boolean(id && id === identity(second));
  } catch {
    return false;
  }
}
