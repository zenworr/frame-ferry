// SPDX-License-Identifier: MIT
import {settings, normalize, sameVideo, heights} from './settings.js';
import {captureVideo, pauseVideos} from './capture.js';

const pending = new Set();
const host = 'frameferry';

export async function inspect(tabId) {
  try {
    const frames = await chrome.scripting.executeScript({target: {tabId}, func: captureVideo});
    return frames[0]?.result || null;
  } catch { return null; }
}
function publicError(error) {
  const message = String(error?.message || error);
  if (/native messaging host|native host|specified native|access.*forbidden/i.test(message)) {
    return 'Frame Ferry could not reach its native host. Run scripts/setup-frameferry for this browser, then reload the extension.';
  }
  return message;
}
async function status(tabId, text, error = false) {
  await chrome.storage.session.set({['status:' + tabId]: {text, error}});
  try {
    await chrome.action.setBadgeText({tabId, text: error ? '!' : pending.has(tabId) ? '…' : ''});
    await chrome.action.setBadgeBackgroundColor({tabId, color: error ? '#b04434' : '#007c83'});
    await chrome.action.setTitle({tabId, title: 'Frame Ferry — ' + text});
  } catch { /* The source tab may have been closed during playback startup. */ }
}
export async function launch(tabId, overrides = {}, link = null) {
  if (pending.has(tabId)) return {ok: false, message: 'A handoff is already in progress for this tab.'};
  pending.add(tabId);
  try {
    const preferences = {...await settings(), ...overrides};
    const options = normalize(preferences);
    const tab = await chrome.tabs.get(tabId);
    let url = link || tab.url;
    if (!/^https?:\/\//i.test(url || '')) throw Error('Open an HTTP or HTTPS video page first. Browser settings and local files cannot be sent.');
    const captured = await inspect(tabId);
    const matches = captured && sameVideo(captured.page, url);
    const position = options.resume ? (matches ? captured.position : null) : 0;
    // Watch URLs support timestamp playback for Shorts and embedded YouTube videos too.
    const parsed = new URL(url);
    if ((parsed.hostname === 'youtube.com' || parsed.hostname.endsWith('.youtube.com')) && /^\/(shorts|embed|live)\//.test(parsed.pathname)) {
      parsed.searchParams.set('v', parsed.pathname.split('/')[2]);
      parsed.pathname = '/watch';
      url = parsed.href;
    }
    await status(tabId, 'Opening mpv. The browser keeps playing until mpv is ready.');
    const response = await chrome.runtime.sendNativeMessage(host, {
      version: 1, action: 'play', url, position, quality: options.quality, fullscreen: options.fullscreen,
    });
    if (!response?.ok) throw Error(response?.message || 'The native host did not confirm playback.');
    let message = 'mpv is playing.';
    if (options.pause) {
      try {
        if (sameVideo((await chrome.tabs.get(tabId)).url, tab.url)) {
          const frames = await chrome.scripting.executeScript({target: {tabId, allFrames: true},
            func: pauseVideos, args: [tab.url]});
          if (frames.some(frame => frame.result === false)) message += ' Some browser videos were left playing because the page could not be verified.';
        } else message += ' The browser tab changed, so it was left playing.';
      } catch { message += ' The browser could not be paused; pause it manually if needed.'; }
    }
    pending.delete(tabId);
    await status(tabId, message);
    return {ok: true, message};
  } catch (error) {
    pending.delete(tabId);
    const message = publicError(error);
    await status(tabId, message, true);
    return {ok: false, message};
  }
}
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (sender.id !== chrome.runtime.id || !sender.url?.startsWith(chrome.runtime.getURL(''))) return false;
  const task = async () => {
    if (message.action === 'inspect') return inspect(message.tabId);
    if (message.action === 'check') {
      try { return await chrome.runtime.sendNativeMessage(host, {version: 1, action: 'check'}); }
      catch (error) { return {ok: false, message: publicError(error)}; }
    }
    if (message.action === 'play' && Number.isInteger(message.tabId) && heights.includes(message.quality)
        && typeof message.resume === 'boolean') return launch(message.tabId, {resume: message.resume, quality: message.quality});
    return {ok: false, message: 'Unknown extension request.'};
  };
  task().then(reply).catch(error => reply({ok: false, message: publicError(error)}));
  return true;
});
chrome.runtime.onInstalled.addListener(async () => {
  await chrome.contextMenus.removeAll();
  chrome.contextMenus.create({id: 'frameferry', title: 'Send to mpv with Frame Ferry', contexts: ['page', 'link', 'video']});
});
chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === 'frameferry' && tab?.id != null) {
    const media = /^https?:\/\//i.test(info.srcUrl || '') ? info.srcUrl : null;
    launch(tab.id, {}, info.linkUrl || (sameVideo(info.pageUrl, tab.url) ? null : media));
  }
});
chrome.tabs.onRemoved.addListener(tabId => chrome.storage.session.remove('status:' + tabId));
