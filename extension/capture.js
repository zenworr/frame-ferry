// SPDX-License-Identifier: MIT
// These functions run in the page's isolated world and use no extension globals.
export function captureVideo() {
  if (document.querySelector('.ad-showing, .ad-interrupting')) return null;
  let video, bestScore = -1, hasMain = false;
  for (const candidate of document.querySelectorAll('video')) {
    const box = candidate.getBoundingClientRect();
    if (box.width <= 0 || box.height <= 0 || candidate.readyState <= 0 || candidate.ended) continue;
    const main = candidate.matches('video.html5-main-video');
    const score = box.width * box.height * (candidate.paused ? 1 : 2);
    if ((main && !hasMain) || (main === hasMain && score > bestScore)) {
      video = candidate;
      bestScore = score;
      hasMain = main;
    }
  }
  if (!video || !Number.isFinite(video.duration) || video.duration <= 0 || !Number.isFinite(video.currentTime)) return null;
  return {position: Math.floor(video.currentTime), page: location.href};
}
export function pauseVideos(expectedPage) {
  // A navigation can occur after the background script checks the tab.
  try {
    if (window.top.location.href !== expectedPage) return false;
  } catch { return false; }
  for (const video of document.querySelectorAll('video')) video.pause();
  return true;
}
