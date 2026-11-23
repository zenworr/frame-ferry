// SPDX-License-Identifier: MIT
// These functions run in the page's isolated world and use no extension globals.
export function captureVideo(expectedPage, token) {
  let capture = true;
  if (token) {
    // A navigation can occur after the background script checks the tab.
    try {
      if (window.top.location.href !== expectedPage) return false;
      capture = window === window.top;
    } catch {
      return false;
    }
  }
  const videos = document.querySelectorAll('video');
  const playingPriority = 2;
  let video,
    bestScore = 0,
    hasMain = false;
  if (capture && !document.querySelector('.ad-showing, .ad-interrupting')) {
    for (const candidate of videos) {
      const box = candidate.getBoundingClientRect();
      if (box.width <= 0 || box.height <= 0 || candidate.readyState <= 0 || candidate.ended) continue;
      const main = candidate.matches('video.html5-main-video');
      const score = box.width * box.height * (candidate.paused ? 1 : playingPriority);
      if ((main && !hasMain) || (main === hasMain && score > bestScore)) {
        video = candidate;
        bestScore = score;
        hasMain = main;
      }
    }
  }
  if (token) {
    window.__frameFerryPause?.release();
    const playing = [];
    window.__frameFerryPause = {token, playing, release: () => playing.forEach((entry) => entry.release())};
    for (const element of videos) {
      if (element.paused) continue;
      const entry = {element, source: element.currentSrc, valid: true, release};
      function release() {
        element.removeEventListener('emptied', invalidate);
        element.removeEventListener('loadstart', invalidate);
      }
      function invalidate() {
        entry.valid = false;
        release();
      }
      element.addEventListener('emptied', invalidate);
      element.addEventListener('loadstart', invalidate);
      playing.push(entry);
      element.pause();
    }
  }
  const captured =
    video && Number.isFinite(video.duration) && video.duration > 0 && Number.isFinite(video.currentTime)
      ? {position: video.currentTime, page: location.href}
      : null;
  return token ? {captured} : captured;
}
export async function finishPause(expectedPage, token, resume) {
  const held = window.__frameFerryPause;
  if (held?.token !== token) return true;
  window.__frameFerryPause = null;
  held.release();
  if (!resume || held.playing.length === 0) return true;
  try {
    if (window.top.location.href !== expectedPage) return false;
  } catch {
    return false;
  }
  const videos = held.playing.filter(
    ({element, source, valid}) =>
      valid &&
      source &&
      source === element.currentSrc &&
      element.readyState > 0 &&
      element.isConnected &&
      element.paused &&
      !element.ended,
  );
  const results = await Promise.allSettled(videos.map(async ({element}) => element.play()));
  return results.every((result) => result.status === 'fulfilled');
}
