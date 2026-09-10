// SPDX-License-Identifier: MIT
// These functions run in the page's isolated world and use no extension globals.
export function captureVideo() {
  if (document.querySelector('.ad-showing, .ad-interrupting')) return null;
  const videos = [...document.querySelectorAll('video')].filter(video => {
    const box = video.getBoundingClientRect();
    return box.width > 0 && box.height > 0 && video.readyState > 0 && !video.ended;
  });
  videos.sort((a, b) => {
    const score = video => {
      const rect = video.getBoundingClientRect();
      return rect.width * rect.height * (video.paused ? 1 : 2);
    };
    return score(b) - score(a);
  });
  const video = videos.find(item => item.matches('video.html5-main-video')) || videos[0];
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
