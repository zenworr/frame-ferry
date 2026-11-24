import assert from 'node:assert/strict';
import {captureVideo, finishPause} from '../extension/capture.js';
import {defaults, normalize, sameVideo} from '../extension/settings.js';

assert.deepEqual(normalize({quality: 999, resume: 'yes', autoContinue: 'true'}), defaults);
assert.equal(defaults.autoContinue, false);
assert.equal(normalize({autoContinue: true}).autoContinue, true);
assert.equal(sameVideo('https://youtu.be/abc?t=7', 'https://www.youtube.com/watch?v=abc'), true);
assert.equal(sameVideo('https://youtube.com.evil.test/watch?v=abc', 'https://www.youtube.com/watch?v=abc'), false);
assert.equal(sameVideo('https://www.youtube.com/watch?v=abc', 'https://www.youtube.com/watch?v=other'), false);
assert.equal(sameVideo('https://video.test/#/one', 'https://video.test/#/two'), false);
assert.equal(sameVideo('https://video.test/#t=17.125', 'https://video.test/#t=npt:00:30,45'), true);
assert.equal(sameVideo('https://video.test/#t=topic', 'https://video.test/'), false);
assert.equal(sameVideo('https://youtube-nocookie.com/embed/abc?t=7', 'https://www.youtube.com/watch?v=abc'), true);
assert.equal(sameVideo('https://www.youtube-nocookie.com/embed/abc', 'https://www.youtube.com/watch?v=abc'), true);
for (const url of ['https://youtu.be/', 'https://www.youtube.com/watch?v=', 'https://youtube-nocookie.com/embed/']) {
  assert.equal(sameVideo(url, url), false);
}
let paused = 0,
  resumed = 0,
  tabUrl = 'https://www.youtube.com/watch?v=abc',
  settings = {},
  nativeReply = {ok: true};
let latest,
  gate,
  writeGate,
  navigateOnPause = false,
  childFrame = false,
  inaccessibleFrame = false,
  calls = [];
const statuses = [];
const storedStatuses = {};
const statusKey = 'status:1';
const tick = () => new Promise((resolve) => setImmediate(resolve));
const pageVideo = Object.assign(new EventTarget(), {
  currentTime: 42,
  duration: 120,
  readyState: 4,
  currentSrc: 'blob:https://example.org/fixture',
  paused: false,
  isConnected: true,
  ended: false,
  getBoundingClientRect: () => ({width: 1000, height: 1}),
  matches: () => true,
  pause() {
    paused++;
    this.currentTime += 0.125;
    this.paused = true;
  },
  async play() {
    resumed++;
    this.paused = false;
  },
});
const childVideo = Object.assign(new EventTarget(), pageVideo, {currentTime: 99, paused: true});
const pageWindow = {location: {href: tabUrl}};
pageWindow.top = pageWindow;
const childWindow = {top: pageWindow};
globalThis.window = pageWindow;
globalThis.location = pageWindow.location;
globalThis.document = {querySelector: () => null, querySelectorAll: () => [pageVideo]};
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
      latest = value;
      const reply = nativeReply;
      if (gate) await gate;
      return reply;
    },
  },
  storage: {
    local: {
      async get() {
        return {preferences: settings};
      },
    },
    session: {
      async get() {
        return {...storedStatuses};
      },
      async set(value) {
        if (writeGate) await writeGate;
        Object.assign(storedStatuses, value);
        statuses.push(value[statusKey]);
      },
      async remove(key) {
        delete storedStatuses[key];
      },
    },
  },
  tabs: {
    async get(tabId) {
      if (tabId !== 1) throw Error('No such tab');
      return {url: tabUrl};
    },
    onRemoved: {
      addListener(fn) {
        this.fn = fn;
      },
    },
  },
  scripting: {
    async executeScript({target, func, args = []}) {
      if (!target.allFrames) {
        calls.push('inspect');
        const inspected = func(...args);
        if (inspected && !pageVideo.paused) pageVideo.currentTime += 2;
        return [{result: inspected}];
      }
      if (func === captureVideo) {
        calls.push('pause');
        if (navigateOnPause) window.top.location.href = 'https://www.youtube.com/watch?v=other';
      } else calls.push('finish');
      const results = [func(...args)];
      if (inaccessibleFrame && func === captureVideo) results.push(false);
      if (childFrame) {
        const topDocument = document;
        globalThis.document = {querySelectorAll: () => [childVideo]};
        globalThis.window = childWindow;
        results.push(func(...args));
        globalThis.window = pageWindow;
        globalThis.document = topDocument;
      }
      return Promise.all(results.map(async (result) => ({result: await result})));
    },
  },
  action: {async setBadgeText() {}, async setBadgeBackgroundColor() {}, async setTitle() {}},
  contextMenus: {onClicked: {addListener() {}}, async removeAll() {}, create() {}},
};
const {launch} = await import('../extension/background.js');
assert.equal((await launch(1)).ok, true);
assert.equal(latest.position, 42.125, 'handoff must capture the final fractional position after pausing');
assert.equal(latest.quality, 2160);
assert.deepEqual(calls, ['pause', 'native', 'finish']);
assert.equal(paused, 1);
assert.equal(pageVideo.paused, true);
assert.equal(statuses[0].pending, true);
assert.equal(statuses[0].page, tabUrl);
assert.equal(statuses.at(-1).pending, false);
assert.equal(statuses[0].token, statuses.at(-1).token);
assert.equal(statuses.at(-1).text, 'mpv is playing.', 'a legacy success reply lost its status');
paused = 0;
pageVideo.paused = false;
calls = [];
settings = {pause: false};
assert.equal((await launch(1, {resume: false, quality: 720})).ok, true);
assert.equal(latest.position, 0);
assert.equal(paused, 0);
assert.equal(latest.quality, 720);
assert.deepEqual(calls, ['inspect', 'native']);
const inspectedTime = pageVideo.currentTime;
assert.equal((await launch(1)).ok, true);
assert.equal(latest.position, inspectedTime);
assert.equal(paused, 0);
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
const failure = {ok: false, message: 'could not play'};
nativeReply = failure;
assert.equal((await launch(1)).ok, false);
assert.equal(paused, 1);
assert.equal(resumed, 1, 'startup failure did not resume the original video');
assert.equal(pageVideo.paused, false);
nativeReply = {ok: true, outcome: 'playing', message: 'mpv is playing.'};
assert.equal((await launch(1, {}, 'https://www.youtube.com/watch?v=other')).message, nativeReply.message);
assert.equal(latest.position, null);
nativeReply = {ok: true, outcome: 'browser', message: 'Return to the browser was requested in mpv.'};
pageVideo.paused = false;
const returned = await launch(1);
assert.deepEqual(returned, {ok: true, message: nativeReply.message});
assert.equal(storedStatuses[statusKey].error, false);
assert.equal(pageVideo.paused, true, 'return to the browser must keep the original video paused');
assert.equal(resumed, 1);
nativeReply = {ok: true};
paused = 0;
pageVideo.paused = false;
pageVideo.currentTime = 42.5;
childVideo.paused = false;
childFrame = true;
let release;
gate = new Promise((resolve) => {
  release = resolve;
});
const first = launch(1);
await tick();
assert.equal(pageVideo.paused, true, 'browser kept playing while mpv started');
assert.equal(childVideo.paused, true, 'handoff did not pause an accessible child frame');
assert.equal(latest.position, 42.625, 'handoff rounded away the top-frame paused position');
pageVideo.currentTime = 53;
assert.equal((await launch(1)).ok, false);
tabUrl = 'https://www.youtube.com/watch?v=new';
window.top.location.href = tabUrl;
release();
assert.equal((await first).ok, true);
assert.equal(resumed, 1, 'handoff resumed a video after navigation');
childFrame = false;
pageVideo.paused = false;
pageVideo.currentTime = 66.25;
nativeReply = failure;
gate = new Promise((resolve) => {
  release = resolve;
});
const failing = launch(1);
await tick();
assert.equal(pageVideo.paused, true);
release();
assert.equal((await failing).ok, false);
assert.equal(resumed, 2, 'a delayed startup failure left the browser paused');
assert.equal(pageVideo.paused, false);
gate = null;
settings = {pause: false};
paused = 0;
assert.equal((await launch(1)).ok, false);
assert.equal(paused, 0, 'disabling browser pausing was ignored');
nativeReply = {ok: true};
settings = {};
tabUrl = pageWindow.location.href = 'https://youtube-nocookie.com/embed/abc?start=7#t=8';
pageVideo.currentTime = 66.25;
assert.equal((await launch(1)).ok, true);
assert.equal(latest.url, 'https://www.youtube.com/watch?start=7&v=abc#t=8');
assert.equal(latest.position, 66.375);
settings = {pause: false};
tabUrl = pageWindow.location.href = 'https://video.test/#/one';
assert.equal((await launch(1, {}, 'https://video.test/#/two')).ok, true);
assert.equal(latest.position, null, 'a different hash-routed video received the current video position');
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
assert.deepEqual(reply, {page: tabUrl, position: 66.375});
paused = 0;

const savedTop = window.top;
Object.defineProperty(window, 'top', {
  configurable: true,
  get() {
    throw Error('Frame access denied');
  },
});
assert.equal(captureVideo(tabUrl, 'test'), false);
assert.equal(paused, 0);
Object.defineProperty(window, 'top', {configurable: true, value: savedTop});
pageVideo.paused = true;
assert.ok(captureVideo(tabUrl, 'test'));
assert.equal(await finishPause(tabUrl, 'test', true), true);
assert.equal(resumed, 2, 'an already paused video was resumed');
pageVideo.paused = false;
assert.ok(captureVideo(tabUrl, 'new'));
assert.equal(await finishPause(tabUrl, 'old', true), true);
assert.equal(resumed, 2, 'old cleanup resumed media held by a new request');
assert.equal(await finishPause(tabUrl, 'new', true), true);
assert.equal(resumed, 3, 'the original playing state was not restored');
const originalPlay = pageVideo.play;
const originalSrc = pageVideo.currentSrc;
for (const reset of [
  () => (pageVideo.currentSrc = 'blob:https://example.org/replacement'),
  () => pageVideo.dispatchEvent(new Event('emptied')),
  () => pageVideo.dispatchEvent(new Event('loadstart')),
]) {
  pageVideo.currentSrc = originalSrc;
  pageVideo.paused = false;
  assert.ok(captureVideo(tabUrl, 'test'));
  reset();
  assert.equal(await finishPause(tabUrl, 'test', true), false, 'rollback reported playback after a source reset');
  assert.equal(resumed, 3, 'rollback resumed a reused video element');
}
pageVideo.paused = false;
assert.ok(captureVideo(tabUrl, 'test'));
await finishPause('https://video.test/new-document', 'test', true);
assert.equal(resumed, 3, 'rollback resumed a video after navigation');
pageVideo.paused = false;
pageVideo.play = () => Promise.reject(Error('autoplay denied'));
assert.ok(captureVideo(tabUrl, 'test'));
assert.equal(await finishPause(tabUrl, 'test', true), false, 'a blocked browser resume was reported as successful');
pageVideo.paused = false;
pageVideo.play = () => new Promise(() => {});
nativeReply = failure;
const delayed = await launch(1);
assert.equal(delayed.ok, false);
assert.match(delayed.message, /playback could not be confirmed/);
assert.equal(storedStatuses[statusKey].pending, false, 'unconfirmed resume locked the tab');
pageVideo.play = originalPlay;
nativeReply = {ok: true};
assert.equal((await launch(1)).ok, true);

let releaseWrite;
writeGate = new Promise((resolve) => {
  releaseWrite = resolve;
});
const closing = launch(1);
await tick();
const removed = chrome.tabs.onRemoved.fn(1);
releaseWrite();
await removed;
await closing;
assert.equal(storedStatuses[statusKey], undefined, 'a delayed status write recreated a closed tab');
writeGate = null;

let releaseOld;
gate = new Promise((resolve) => {
  releaseOld = resolve;
});
nativeReply = failure;
const old = launch(1);
await tick();
const oldToken = storedStatuses[statusKey].token;
await chrome.tabs.onRemoved.fn(1);
nativeReply = {ok: true};
gate = new Promise((resolve) => {
  release = resolve;
});
pageVideo.paused = false;
const newer = launch(1);
await tick();
const newerStatus = storedStatuses[statusKey];
assert.notEqual(newerStatus.token, oldToken);
releaseOld();
await old;
assert.equal(storedStatuses[statusKey], newerStatus, 'an old reply overwrote a newer pending status');
assert.equal(pageVideo.paused, true, 'an old failure resumed media owned by the new request');
release();
assert.equal((await newer).ok, true);
assert.equal(storedStatuses[statusKey].token, newerStatus.token);
assert.equal(storedStatuses[statusKey].pending, false);
gate = new Promise((resolve) => {
  release = resolve;
});
const duringStartup = launch(1);
await tick();
assert.equal(storedStatuses[statusKey].pending, true);
await chrome.tabs.onRemoved.fn(1);
release();
await duringStartup;
assert.equal(storedStatuses[statusKey], undefined, 'a late startup reply recreated a closed tab');
gate = null;
assert.equal((await launch(2)).ok, false);
assert.equal(storedStatuses['status:2'], undefined, 'a launch for a missing tab created a status');

storedStatuses[statusKey] = {page: tabUrl, token: 'lost', text: 'Opening mpv.', pending: true};
captureVideo(tabUrl, 'lost');
calls = [];
const restarted = await import('../extension/background.js?restarted');
await new Promise((resolve) =>
  chrome.runtime.onMessage.fn(
    {action: 'inspect', tabId: 1},
    {id: 'fixture', url: 'chrome-extension://fixture/popup.html'},
    resolve,
  ),
);
const interrupted = storedStatuses[statusKey];
assert.equal(interrupted.pending, false);
assert.equal(interrupted.interrupted, true);
assert.match(interrupted.text, /Handoff interrupted/);
assert.deepEqual(calls, ['inspect'], 'activation replayed a launch or rolled back an unknown outcome');
assert.equal((await restarted.launch(1)).ok, true);
assert.equal(storedStatuses[statusKey].interrupted, undefined);

const video = (area, time, extra = {}) =>
  Object.assign(new EventTarget(), {
    readyState: 4,
    ended: false,
    paused: false,
    currentTime: time,
    duration: 120,
    getBoundingClientRect: () => ({width: area, height: 1}),
    matches: () => false,
    pause() {
      this.paused = true;
    },
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
document.querySelectorAll = () => [video(150, 30, {paused: true}), video(100, 45)];
assert.equal(captureVideo(tabUrl, 'priority').captured.position, 45, 'pausing changed which video was selected');
await finishPause(tabUrl, 'priority', false);
const stream = {};
for (const [source, replacement, canResume] of [
  [stream, stream, true],
  [stream, {}, false],
  [null, null, false],
]) {
  let plays = 0;
  const heldVideo = video(100, 20, {
    currentSrc: '',
    srcObject: source,
    isConnected: true,
    async play() {
      plays++;
      this.paused = false;
    },
  });
  document.querySelectorAll = () => [heldVideo];
  assert.ok(captureVideo(tabUrl, 'source'));
  assert.equal(heldVideo.paused, true);
  heldVideo.srcObject = replacement;
  assert.equal(await finishPause(tabUrl, 'source', true), canResume, 'rollback misreported playback');
  assert.equal(plays, Number(canResume), 'rollback did not respect the paused media source');
  assert.equal(heldVideo.paused, !canResume);
}
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
  position = 42,
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
        return message.action === 'inspect' ? {position} : await playResponse;
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
for (const [position, clock] of [
  [3599, '59:59'],
  [3600, '1:00:00'],
  [4503, '1:15:03'],
]) {
  const panel = await openPopup({}, undefined, undefined, null, position);
  assert.equal(panel.elements.get('position').textContent.split(' · ')[0], `At ${clock}`);
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
popup = await openPopup({autoContinue: true}, page, undefined, interrupted);
assert.equal(popup.elements.get('send').disabled, false);
assert.equal(popup.plays().length, 0, 'auto-continue replayed an interrupted handoff');
assert.equal(popup.elements.get('status').textContent, interrupted.text);
await popup.elements.get('send').listeners.click();
assert.equal(popup.plays().length, 1, 'an interrupted handoff blocked a manual retry');
console.log(
  'Frame Ferry: settings, identity, timestamps, readiness, pause, navigation, duplicate requests, capture and popup passed.',
);
