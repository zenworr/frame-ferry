// SPDX-License-Identifier: MIT
// These functions run in the page's isolated world and use no extension globals.
export function captureVideo() {
  if (document.querySelector('.ad-showing, .ad-interrupting')) return null;
  const playingPriority = 2;
  let video,
    bestScore = 0,
    hasMain = false;
  for (const candidate of document.querySelectorAll('video')) {
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
  if (!video || !Number.isFinite(video.duration) || video.duration <= 0 || !Number.isFinite(video.currentTime))
    return null;
  return {position: video.currentTime, page: location.href};
}
export function pauseVideos(expectedPage) {
  // A navigation can occur after the background script checks the tab.
  try {
    if (window.top.location.href !== expectedPage) return false;
  } catch {
    return false;
  }
  const playing = [];
  window.__frameFerryPausedVideos = playing;
  for (const video of document.querySelectorAll('video')) {
    if (!video.paused) {
      playing.push(video);
      video.pause();
    }
  }
  return true;
}
export async function finishPause(expectedPage, resume) {
  const playing = window.__frameFerryPausedVideos || [];
  window.__frameFerryPausedVideos = null;
  if (!resume || playing.length === 0) return true;
  try {
    if (window.top.location.href !== expectedPage) return false;
  } catch {
    return false;
  }
  const results = await Promise.allSettled(
    playing.filter((video) => video.isConnected && video.paused && !video.ended).map((video) => video.play()),
  );
  return results.every((result) => result.status === 'fulfilled');
}
