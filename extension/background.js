// SPDX-License-Identifier: MIT
import {settings, normalize, sameVideo, heights, isYouTubeNoCookie, youtubeVideoId} from './settings.js';
import {captureVideo, finishPause} from './capture.js';

const pending = new Map();
const host = 'frameferry';
const statusPrefix = 'status:';
const rollbackTimeoutMs = 500;
let statusChanges = Promise.resolve();

function updateStatus(action) {
  // Keep tab removal ordered after any status write already in progress.
  const task = statusChanges.then(action);
  statusChanges = task.catch(() => {});
  return task;
}

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
async function writeStatus(tabId, state) {
  await chrome.storage.session.set({[statusPrefix + tabId]: state});
  try {
    await chrome.action.setBadgeText({tabId, text: state.error ? '!' : state.pending ? '…' : ''});
    await chrome.action.setBadgeBackgroundColor({tabId, color: state.error ? '#b04434' : '#007c83'});
    await chrome.action.setTitle({tabId, title: 'Frame Ferry — ' + state.text});
  } catch {
    /* The source tab may have been closed during playback startup. */
  }
}
function status(tabId, token, state) {
  return updateStatus(async () => {
    if (pending.get(tabId) !== token) return;
    await writeStatus(tabId, {...state, token});
  });
}
const activated = updateStatus(async () => {
  for (const [key, state] of Object.entries(await chrome.storage.session.get(null))) {
    if (!key.startsWith(statusPrefix) || !state?.pending) continue;
    await writeStatus(Number(key.slice(statusPrefix.length)), {
      ...state,
      pending: false,
      interrupted: true,
      error: true,
      text: 'Handoff interrupted. Check mpv and the browser before you try again.',
    });
  }
});
export async function launch(tabId, overrides = {}, link = null) {
  await activated;
  if (pending.has(tabId)) return {ok: false, message: 'A handoff is already in progress for this tab.'};
  const token = crypto.randomUUID();
  pending.set(tabId, token);
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
    await status(tabId, token, {
      page,
      text: options.pause ? 'Pausing the browser while mpv starts.' : 'Opening mpv.',
      pending: true,
      error: false,
    });
    if (pending.get(tabId) !== token) throw Error('The source tab closed during handoff.');
    let captured,
      incompletePause = false;
    if (options.pause) {
      held = true;
      const frames = await chrome.scripting.executeScript({
        target: {tabId, allFrames: true},
        func: captureVideo,
        args: [page, token],
      });
      const top = frames[0]?.result;
      if (!top) throw Error('The page changed before it could be paused. Try again.');
      captured = top.captured;
      incompletePause = frames.some((frame) => !frame.result);
      if ((await chrome.tabs.get(tabId)).url !== page) throw Error('The page changed during handoff. Try again.');
    } else captured = await inspect(tabId);
    if (pending.get(tabId) !== token) throw Error('The source tab closed during handoff.');
    const matches = captured && sameVideo(captured.page, url);
    const position = options.resume ? (matches ? captured.position : null) : 0;
    // Watch URLs support timestamp playback for Shorts and embedded YouTube videos too.
    const parsed = new URL(url);
    const id = youtubeVideoId(parsed);
    if (id && parsed.hostname !== 'youtu.be' && /^\/(shorts|embed|live)\//.test(parsed.pathname)) {
      if (isYouTubeNoCookie(parsed.hostname)) {
        parsed.protocol = 'https:';
        parsed.hostname = 'www.youtube.com';
        parsed.port = '';
      }
      parsed.searchParams.set('v', id);
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
    const message =
      response.message ||
      (response.outcome === 'browser' ? 'Return to the browser was requested in mpv.' : 'mpv is playing.');
    result = {
      ok: true,
      message: message + (incompletePause ? ' Some browser frames could not be paused or verified.' : ''),
    };
  } catch (error) {
    result = {ok: false, message: publicError(error)};
  }
  if (held && pending.get(tabId) === token) {
    let timer;
    try {
      const frames = await Promise.race([
        chrome.scripting.executeScript({
          target: {tabId, allFrames: true},
          func: finishPause,
          args: [page, token, !result.ok],
        }),
        // A background tab can delay play() until the user selects it.
        new Promise((resolve) => {
          timer = setTimeout(() => resolve(null), rollbackTimeoutMs);
        }),
      ]);
      if (!result.ok && (!frames || frames.some((frame) => frame.result === false)))
        result.message += ' Browser playback could not be confirmed; check the tab.';
    } catch {
      if (!result.ok) result.message += ' Browser playback could not be confirmed; check the tab.';
    } finally {
      clearTimeout(timer);
    }
  }
  try {
    if (page) await status(tabId, token, {page, text: result.message, error: !result.ok, pending: false});
  } finally {
    if (pending.get(tabId) === token) pending.delete(tabId);
  }
  return result;
}
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (sender.id !== chrome.runtime.id || !sender.url?.startsWith(chrome.runtime.getURL(''))) return false;
  const task = async () => {
    if (message.action === 'inspect') {
      await activated;
      return inspect(message.tabId);
    }
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
chrome.tabs.onRemoved.addListener((tabId) => {
  pending.delete(tabId);
  return updateStatus(() => chrome.storage.session.remove(statusPrefix + tabId));
});
