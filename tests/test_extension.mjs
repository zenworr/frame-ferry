import assert from 'node:assert/strict';
import {captureVideo, finishPause, pauseVideos} from '../extension/capture.js';
import {defaults, normalize, sameVideo} from '../extension/settings.js';

assert.deepEqual(normalize({quality: 999, resume: 'yes', autoContinue: 'true'}), defaults);
assert.equal(defaults.autoContinue, false);
assert.equal(normalize({autoContinue: true}).autoContinue, true);
assert.equal(sameVideo('https://youtu.be/abc?t=7', 'https://www.youtube.com/watch?v=abc'), true);
assert.equal(sameVideo('https://youtube.com.evil.test/watch?v=abc', 'https://www.youtube.com/watch?v=abc'), false);
assert.equal(sameVideo('https://www.youtube.com/watch?v=abc', 'https://www.youtube.com/watch?v=other'), false);
let paused = 0,
  resumed = 0,
  tabUrl = 'https://www.youtube.com/watch?v=abc',
  settings = {},
  fail = false,
  captured = {position: 42, page: tabUrl};
let latest,
  gate,
  navigateOnPause = false,
  inaccessibleFrame = false,
  calls = [];
const statuses = [];
const pageVideo = {
  paused: false,
  isConnected: true,
  ended: false,
  pause() {
    paused++;
    this.paused = true;
  },
  async play() {
    resumed++;
    this.paused = false;
  },
};
globalThis.window = {top: {location: {href: tabUrl}}};
globalThis.document = {querySelectorAll: () => [pageVideo]};
globalThis.chrome = {
  runtime: {
    id: 'fixture',
    getURL: () => 'chrome-extension://fixture/',
    onMessage: {
      addListener(fn) {
        this.fn = fn;
      },
    },
    onInstalled: {addListener() {}},
    async sendNativeMessage(name, value) {
      calls.push('native');
      assert.equal(name, 'frameferry');
      assert.equal(paused, settings.pause === false ? 0 : 1);
      latest = value;
      if (gate) await gate;
      if (fail) return {ok: false, message: 'could not play'};
      return {ok: true};
    },
  },
  storage: {
    local: {
      async get() {
        return {preferences: settings};
      },
    },
    session: {
      async set(value) {
        statuses.push(value['status:1']);
      },
      async remove() {},
    },
  },
  tabs: {
    async get() {
      return {url: tabUrl};
    },
    onRemoved: {addListener() {}},
  },
  scripting: {
    async executeScript({target, func, args = []}) {
      if (target.allFrames) {
        if (func === pauseVideos) {
          calls.push('pause');
          if (navigateOnPause) window.top.location.href = 'https://www.youtube.com/watch?v=other';
        } else calls.push('finish');
        const result = [{result: await func(...args)}];
        if (inaccessibleFrame && func === pauseVideos) result.push({result: false});
        return result;
      }
      return [{result: captured}];
    },
  },
  action: {async setBadgeText() {}, async setBadgeBackgroundColor() {}, async setTitle() {}},
  contextMenus: {onClicked: {addListener() {}}, async removeAll() {}, create() {}},
};
const {launch} = await import('../extension/background.js');
assert.equal((await launch(1)).ok, true);
assert.equal(latest.position, 42);
assert.equal(latest.quality, 2160);
assert.deepEqual(calls, ['pause', 'native', 'finish']);
assert.equal(paused, 1);
assert.equal(pageVideo.paused, true);
assert.equal(statuses[0].pending, true);
assert.equal(statuses[0].page, tabUrl);
assert.equal(statuses.at(-1).pending, false);
paused = 0;
pageVideo.paused = false;
calls = [];
settings = {pause: false};
assert.equal((await launch(1, {resume: false, quality: 720})).ok, true);
assert.equal(latest.position, 0);
assert.equal(paused, 0);
assert.equal(latest.quality, 720);
settings = {};
pageVideo.paused = false;
inaccessibleFrame = true;
paused = 0;
const partial = await launch(1);
assert.equal(partial.ok, true);
assert.match(partial.message, /Some browser frames/);
inaccessibleFrame = false;
paused = 0;
pageVideo.paused = false;
navigateOnPause = true;
const changed = await launch(1);
assert.equal(changed.ok, false);
assert.equal(paused, 0);
assert.match(changed.message, /page changed/);
navigateOnPause = false;
window.top.location.href = tabUrl;
pageVideo.paused = false;
fail = true;
assert.equal((await launch(1)).ok, false);
assert.equal(paused, 1);
assert.equal(resumed, 1, 'startup failure did not resume the original video');
assert.equal(pageVideo.paused, false);
fail = false;
paused = 0;
captured = {position: 99, page: 'https://www.youtube.com/watch?v=other'};
await launch(1);
assert.equal(latest.position, null);
paused = 0;
pageVideo.paused = false;
captured = {position: 42.625, page: tabUrl};
let release;
gate = new Promise((resolve) => {
  release = resolve;
});
const first = launch(1);
await new Promise((resolve) => setTimeout(resolve, 0));
assert.equal(pageVideo.paused, true, 'browser kept playing while mpv started');
assert.equal(latest.position, 42.625, 'handoff rounded away the paused position');
captured.position = 53;
assert.equal((await launch(1)).ok, false);
tabUrl = 'https://www.youtube.com/watch?v=new';
window.top.location.href = tabUrl;
release();
assert.equal((await first).ok, true);
assert.equal(resumed, 1, 'handoff resumed a video after navigation');
gate = null;
paused = 0;
pageVideo.paused = false;
captured = {position: 66.25, page: tabUrl};
gate = new Promise((resolve) => {
  release = resolve;
});
const failing = launch(1);
await new Promise((resolve) => setTimeout(resolve, 0));
assert.equal(pageVideo.paused, true);
fail = true;
release();
assert.equal((await failing).ok, false);
assert.equal(resumed, 2, 'a delayed startup failure left the browser paused');
assert.equal(pageVideo.paused, false);
fail = false;
gate = null;
settings = {pause: false};
paused = 0;
fail = true;
assert.equal((await launch(1)).ok, false);
assert.equal(paused, 0, 'disabling browser pausing was ignored');
fail = false;
settings = {};
assert.equal(
  chrome.runtime.onMessage.fn({action: 'play'}, {id: 'other', url: 'https://evil.test'}, () => {}),
  false,
);
assert.equal(
  chrome.runtime.onMessage.fn({action: 'play'}, {id: 'fixture', url: tabUrl, tab: {id: 1}}, () => {}),
  false,
);
const reply = await new Promise((resolve) =>
  chrome.runtime.onMessage.fn(
    {action: 'inspect', tabId: 1},
    {id: 'fixture', url: 'chrome-extension://fixture/popup.html', tab: {id: 2}},
    resolve,
  ),
);
assert.deepEqual(reply, captured);
paused = 0;

const savedTop = window.top;
Object.defineProperty(window, 'top', {
  configurable: true,
  get() {
    throw Error('Frame access denied');
  },
});
assert.equal(pauseVideos(tabUrl), false);
assert.equal(paused, 0);
Object.defineProperty(window, 'top', {configurable: true, value: savedTop});
pageVideo.paused = true;
assert.equal(pauseVideos(tabUrl), true);
assert.equal(await finishPause(tabUrl, true), true);
assert.equal(resumed, 2, 'an already paused video was resumed');
pageVideo.paused = false;
assert.equal(pauseVideos(tabUrl), true);
assert.equal(await finishPause(tabUrl, true), true);
assert.equal(resumed, 3, 'the original playing state was not restored');
const originalPlay = pageVideo.play;
pageVideo.play = () => Promise.reject(Error('autoplay denied'));
assert.equal(pauseVideos(tabUrl), true);
assert.equal(await finishPause(tabUrl, true), false, 'a blocked browser resume was reported as successful');
pageVideo.play = originalPlay;

const video = (area, time, extra = {}) => ({
  readyState: 4,
  ended: false,
  paused: false,
  currentTime: time,
  duration: 120,
  getBoundingClientRect: () => ({width: area, height: 1}),
  matches: () => false,
  ...extra,
});
globalThis.location = {href: 'https://example.org/video'};
globalThis.document = {
  querySelector: () => null,
  querySelectorAll: () => [video(0, 9), video(100, 20), video(1000, 40)],
};
assert.equal(captureVideo().position, 40);
document.querySelectorAll = () => [video(1000, 40.625)];
assert.equal(captureVideo().position, 40.625);
let layoutReads = 0;
const candidates = Array.from({length: 100}, (_, i) =>
  video(i + 1, i, {
    getBoundingClientRect() {
      layoutReads++;
      return {width: i + 1, height: 1};
    },
  }),
);
document.querySelectorAll = () => candidates;
assert.equal(captureVideo().position, 99);
assert.equal(layoutReads, 100, 'capture repeatedly read the same video layout');
candidates[3].matches = () => true;
assert.equal(captureVideo().position, 3, 'the main YouTube video lost priority');
candidates[3].ended = true;
assert.equal(captureVideo().position, 99);
document.querySelector = () => ({});
assert.equal(captureVideo(), null);
document.querySelector = () => null;
document.querySelectorAll = () => [video(1000, 40, {duration: Infinity})];
assert.equal(captureVideo(), null);
let popupCount = 0;
async function openPopup(
  preferences = {},
  url = 'https://example.org/video',
  playResponse = {ok: true, message: 'Ready'},
  status = null,
) {
  const elements = new Map();
  globalThis.document = {
    getElementById(id) {
      if (!elements.has(id))
        elements.set(id, {
          checked: false,
          disabled: true,
          value: '',
          classList: {toggle() {}},
          listeners: {},
          addEventListener(event, handler) {
            this.listeners[event] = handler;
          },
        });
      return elements.get(id);
    },
  };
  const messages = [],
    saved = [],
    changed = [];
  globalThis.chrome = {
    storage: {
      onChanged: {
        addListener(fn) {
          changed.push(fn);
        },
      },
      local: {
        async get() {
          return {preferences};
        },
        async set(value) {
          saved.push(value.preferences);
        },
      },
      session: {
        async get() {
          return {'status:7': status};
        },
      },
    },
    tabs: {
      async query() {
        return [{id: 7, title: 'Video', url}];
      },
    },
    runtime: {
      async sendMessage(message) {
        messages.push(message);
        return message.action === 'inspect' ? {position: 42} : await playResponse;
      },
    },
  };
  await import(`../extension/popup.js?test=${++popupCount}`);
  await new Promise((resolve) => setImmediate(resolve));
  return {
    elements,
    saved,
    plays: () => messages.filter((message) => message.action === 'play'),
    status(value) {
      for (const fn of changed) fn({'status:7': {newValue: value}}, 'session');
    },
  };
}
let popup = await openPopup();
popup.elements.get('default-quality').value = '720';
await popup.elements.get('default-quality').listeners.change();
assert.equal(popup.elements.get('quality').value, '720');
popup.elements.get('quality').value = '1080';
popup.elements.get('default-quality').value = '480';
await popup.elements.get('default-quality').listeners.change();
assert.equal(popup.elements.get('quality').value, '1080', 'saving a default replaced the explicit per-launch quality');
popup = await openPopup();
assert.equal(popup.elements.get('autoContinue').checked, false);
assert.equal(popup.plays().length, 0);
popup.elements.get('autoContinue').checked = true;
await popup.elements.get('autoContinue').listeners.change();
assert.equal(popup.saved[0].autoContinue, true);
assert.equal(popup.plays().length, 0); // Changing the setting does not start playback.
popup = await openPopup(popup.saved[0]);
assert.deepEqual(popup.plays(), [{action: 'play', tabId: 7, resume: true, quality: 2160}]);
assert.equal(popup.elements.get('status').textContent, 'Ready');
popup = await openPopup({autoContinue: true, resume: false, quality: 720});
assert.equal(popup.plays()[0].resume, true);
assert.equal(popup.plays()[0].quality, 720);
popup = await openPopup({autoContinue: true}, 'chrome://extensions');
assert.equal(popup.plays().length, 0);
assert.equal(popup.elements.get('send').disabled, true);
let finishPlay;
popup = await openPopup(
  {autoContinue: true},
  undefined,
  new Promise((resolve) => {
    finishPlay = resolve;
  }),
);
assert.equal(popup.elements.get('send').disabled, true);
await popup.elements.get('send').listeners.click();
assert.equal(popup.plays().length, 1);
finishPlay({ok: false, message: 'Could not play'});
await new Promise((resolve) => setImmediate(resolve));
assert.equal(popup.elements.get('status').textContent, 'Could not play');
assert.equal(popup.elements.get('send').disabled, false);
popup.elements.get('autoContinue').checked = false;
await popup.elements.get('autoContinue').listeners.change();
popup = await openPopup(popup.saved[0]);
assert.equal(popup.plays().length, 0);
const page = 'https://example.org/video';
const opening = {page, text: 'Opening mpv', pending: true};
popup = await openPopup({autoContinue: true}, page, undefined, opening);
assert.equal(popup.plays().length, 0, 'reopening a pending handoff started another request');
assert.equal(popup.elements.get('send').disabled, true);
assert.equal(popup.elements.get('status').textContent, 'Opening mpv');
await popup.elements.get('alternate').listeners.click();
assert.equal(popup.plays().length, 0);
popup.status({page, text: 'mpv is playing.', pending: false});
assert.equal(popup.elements.get('status').textContent, 'mpv is playing.');
assert.equal(popup.elements.get('send').disabled, false);
popup.status({page, text: 'Player log: /private/player.log', error: true, pending: false});
assert.equal(popup.elements.get('status').textContent, 'Player log: /private/player.log');
popup = await openPopup({}, 'https://example.org/other', undefined, {page, text: 'Old success', pending: false});
assert.equal(popup.elements.get('status').textContent, '');
popup = await openPopup({autoContinue: true}, 'https://example.org/other', undefined, opening);
assert.equal(popup.elements.get('send').disabled, true);
assert.equal(popup.plays().length, 0);
assert.match(popup.elements.get('status').textContent, /still in progress/);
popup.status({page, text: 'Old success', pending: false});
assert.equal(popup.elements.get('send').disabled, false);
assert.equal(popup.elements.get('status').textContent, '');
console.log(
  'Frame Ferry: settings, identity, timestamps, readiness, pause, navigation, duplicate requests, capture and popup passed.',
);
