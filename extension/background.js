// SPDX-License-Identifier: MIT
import {settings, normalize, sameVideo, heights} from './settings.js';
import {captureVideo, pauseVideos, finishPause} from './capture.js';

const pending = new Set();
const host = 'frameferry';

export async function inspect(tabId) {
  try {
    const frames = await chrome.scripting.executeScript({target: {tabId}, func: captureVideo});
    return frames[0]?.result || null;
  } catch {
    return null;
  }
}
function publicError(error) {
  const message = String(error?.message || error);
  if (/native messaging host|native host|specified native|access.*forbidden/i.test(message)) {
    return 'Frame Ferry could not reach its native host. Run scripts/setup-frameferry for this browser, then reload the extension.';
  }
  return message;
}
async function status(tabId, page, text, error = false) {
  await chrome.storage.session.set({['status:' + tabId]: {page, text, error, pending: pending.has(tabId)}});
  try {
    await chrome.action.setBadgeText({tabId, text: error ? '!' : pending.has(tabId) ? '…' : ''});
    await chrome.action.setBadgeBackgroundColor({tabId, color: error ? '#b04434' : '#007c83'});
    await chrome.action.setTitle({tabId, title: 'Frame Ferry — ' + text});
  } catch {
    /* The source tab may have been closed during playback startup. */
  }
}
export async function launch(tabId, overrides = {}, link = null) {
  if (pending.has(tabId)) return {ok: false, message: 'A handoff is already in progress for this tab.'};
  pending.add(tabId);
  let page = null,
    held = false,
    result;
  try {
    const preferences = {...(await settings()), ...overrides};
    const options = normalize(preferences);
    const tab = await chrome.tabs.get(tabId);
    page = tab.url;
    let url = link || tab.url;
    if (!/^https?:\/\//i.test(url || ''))
      throw Error('Open an HTTP or HTTPS video page first. Browser settings and local files cannot be sent.');
    await status(tabId, page, options.pause ? 'Pausing the browser while mpv starts.' : 'Opening mpv.');
    const captured = await inspect(tabId);
    const matches = captured && sameVideo(captured.page, url);
    const position = options.resume ? (matches ? captured.position : null) : 0;
    let incompletePause = false;
    if (options.pause) {
      held = true;
      const frames = await chrome.scripting.executeScript({
        target: {tabId, allFrames: true},
        func: pauseVideos,
        args: [page],
      });
      if (frames[0]?.result !== true) throw Error('The page changed before it could be paused. Try again.');
      incompletePause = frames.some((frame) => frame.result !== true);
      if ((await chrome.tabs.get(tabId)).url !== page) throw Error('The page changed during handoff. Try again.');
    }
    // Watch URLs support timestamp playback for Shorts and embedded YouTube videos too.
    const parsed = new URL(url);
    if (
      (parsed.hostname === 'youtube.com' || parsed.hostname.endsWith('.youtube.com')) &&
      /^\/(shorts|embed|live)\//.test(parsed.pathname)
    ) {
      parsed.searchParams.set('v', parsed.pathname.split('/')[2]);
      parsed.pathname = '/watch';
      url = parsed.href;
    }
    const response = await chrome.runtime.sendNativeMessage(host, {
      version: 1,
      action: 'play',
      url,
      position,
      quality: options.quality,
      fullscreen: options.fullscreen,
    });
    if (!response?.ok) throw Error(response?.message || 'The native host did not confirm playback.');
    result = {
      ok: true,
      message: 'mpv is playing.' + (incompletePause ? ' Some browser frames could not be paused or verified.' : ''),
    };
  } catch (error) {
    result = {ok: false, message: publicError(error)};
  } finally {
    if (held) {
      try {
        const frames = await chrome.scripting.executeScript({
          target: {tabId, allFrames: true},
          func: finishPause,
          args: [page, !result?.ok],
        });
        if (!result?.ok && frames.some((frame) => frame.result === false))
          result.message += ' Some browser videos could not be resumed; check the tab.';
      } catch {
        if (!result?.ok) result.message += ' The browser could not be resumed; check the tab.';
      }
    }
    pending.delete(tabId);
  }
  await status(tabId, page, result.message, !result.ok);
  return result;
}
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (sender.id !== chrome.runtime.id || !sender.url?.startsWith(chrome.runtime.getURL(''))) return false;
  const task = async () => {
    if (message.action === 'inspect') return inspect(message.tabId);
    if (message.action === 'check') {
      try {
        return await chrome.runtime.sendNativeMessage(host, {version: 1, action: 'check'});
      } catch (error) {
        return {ok: false, message: publicError(error)};
      }
    }
    if (
      message.action === 'play' &&
      Number.isInteger(message.tabId) &&
      heights.includes(message.quality) &&
      typeof message.resume === 'boolean'
    )
      return launch(message.tabId, {resume: message.resume, quality: message.quality});
    return {ok: false, message: 'Unknown extension request.'};
  };
  task()
    .then(reply)
    .catch((error) => reply({ok: false, message: publicError(error)}));
  return true;
});
chrome.runtime.onInstalled.addListener(async () => {
  await chrome.contextMenus.removeAll();
  chrome.contextMenus.create({
    id: 'frameferry',
    title: 'Send to mpv with Frame Ferry',
    contexts: ['page', 'link', 'video'],
  });
});
chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === 'frameferry' && Number.isInteger(tab?.id)) {
    const media = /^https?:\/\//i.test(info.srcUrl || '') ? info.srcUrl : null;
    launch(tab.id, {}, info.linkUrl || (sameVideo(info.pageUrl, tab.url) ? null : media));
  }
});
chrome.tabs.onRemoved.addListener((tabId) => chrome.storage.session.remove('status:' + tabId));
