import assert from 'node:assert/strict';
import {captureVideo, pauseVideos} from '../extension/capture.js';
import {defaults, normalize, sameVideo} from '../extension/settings.js';

assert.deepEqual(normalize({quality: 999, resume: 'yes', autoContinue: 'true'}), defaults);
assert.equal(defaults.autoContinue, false);
assert.equal(normalize({autoContinue: true}).autoContinue, true);
assert.equal(sameVideo('https://youtu.be/abc?t=7', 'https://www.youtube.com/watch?v=abc'), true);
assert.equal(sameVideo('https://youtube.com.evil.test/watch?v=abc', 'https://www.youtube.com/watch?v=abc'), false);
assert.equal(sameVideo('https://www.youtube.com/watch?v=abc', 'https://www.youtube.com/watch?v=other'), false);
let paused = 0, tabUrl = 'https://www.youtube.com/watch?v=abc', settings = {}, fail = false, captured = {position: 42, page: tabUrl};
let latest, gate, navigateOnPause = false, calls = [];
globalThis.window = {top: {location: {href: tabUrl}}};
globalThis.document = {querySelectorAll: () => [{pause() { paused++; }}]};
globalThis.chrome = {
 runtime: {id: 'fixture', getURL: () => 'chrome-extension://fixture/', onMessage: {addListener(fn) { this.fn = fn; }},
  onInstalled: {addListener() {}}, async sendNativeMessage(name, value) {
   calls.push('native'); assert.equal(name, 'frameferry'); assert.equal(paused, 0); latest = value;
   if (gate) await gate;
   if (fail) return {ok: false, message: 'could not play'};
   return {ok: true};
  }},
 storage: {local: {async get() { return {preferences: settings}; }}, session: {async set() {}, async remove() {}}},
 tabs: {async get() { return {url: tabUrl}; }, onRemoved: {addListener() {}}},
 scripting: {async executeScript({target, func, args = []}) {
   if (target.allFrames) {
    calls.push('pause');
    if (navigateOnPause) window.top.location.href = 'https://www.youtube.com/watch?v=other';
    return [{result: func(...args)}];
   }
   return [{result: captured}];
 }},
 action: {async setBadgeText() {}, async setBadgeBackgroundColor() {}, async setTitle() {}},
 contextMenus: {onClicked: {addListener() {}}, async removeAll() {}, create() {}},
};
const {launch} = await import('../extension/background.js');
assert.equal((await launch(1)).ok, true);
assert.equal(latest.position, 42); assert.equal(latest.quality, 2160);
assert.deepEqual(calls, ['native', 'pause']);
assert.equal(paused, 1);
paused = 0; calls = []; settings = {pause: false};
assert.equal((await launch(1, {resume: false, quality: 720})).ok, true);
assert.equal(latest.position, 0); assert.equal(paused, 0); assert.equal(latest.quality, 720);
settings = {}; navigateOnPause = true;
const changed = await launch(1);
assert.equal(changed.ok, true); assert.equal(paused, 0);
assert.match(changed.message, /could not be verified/);
navigateOnPause = false; window.top.location.href = tabUrl;
fail = true;
assert.equal((await launch(1)).ok, false); assert.equal(paused, 0);
fail = false; captured = {position: 99, page: 'https://www.youtube.com/watch?v=other'};
await launch(1); assert.equal(latest.position, null);
paused = 0;
let release; gate = new Promise(resolve => { release = resolve; });
const first = launch(1);
await new Promise(resolve => setTimeout(resolve, 0));
assert.equal((await launch(1)).ok, false);
tabUrl = 'https://www.youtube.com/watch?v=new';
release(); assert.equal((await first).ok, true); assert.equal(paused, 0); gate = null;
assert.equal(chrome.runtime.onMessage.fn({action: 'play'}, {id: 'other', url: 'https://evil.test'}, () => {}), false);
assert.equal(chrome.runtime.onMessage.fn({action: 'play'}, {id: 'fixture', url: tabUrl, tab: {id: 1}}, () => {}), false);
const reply = await new Promise(resolve => chrome.runtime.onMessage.fn({action: 'inspect', tabId: 1},
 {id: 'fixture', url: 'chrome-extension://fixture/popup.html', tab: {id: 2}}, resolve));
assert.deepEqual(reply, captured);

const savedTop = window.top;
Object.defineProperty(window, 'top', {configurable: true, get() { throw Error('Frame access denied'); }});
assert.equal(pauseVideos(tabUrl), false); assert.equal(paused, 0);
Object.defineProperty(window, 'top', {configurable: true, value: savedTop});

const video = (area, time, extra = {}) => ({readyState: 4, ended: false, paused: false, currentTime: time,
 duration: 120, getBoundingClientRect: () => ({width: area, height: 1}), matches: () => false, ...extra});
globalThis.location = {href: 'https://example.org/video'};
globalThis.document = {querySelector: () => null, querySelectorAll: () => [video(0, 9), video(100, 20), video(1000, 40)]};
assert.equal(captureVideo().position, 40);
document.querySelector = () => ({}); assert.equal(captureVideo(), null);
document.querySelector = () => null; document.querySelectorAll = () => [video(1000, 40, {duration: Infinity})];
assert.equal(captureVideo(), null);
let popupCount = 0;
async function openPopup(preferences = {}, url = 'https://example.org/video', playResponse = {ok: true, message: 'Ready'}) {
 const elements = new Map();
 globalThis.document = {getElementById(id) {
  if (!elements.has(id)) elements.set(id, {checked: false, disabled: true, value: '',
   classList: {toggle() {}}, listeners: {}, addEventListener(event, handler) { this.listeners[event] = handler; }});
  return elements.get(id);
 }};
 const messages = [], saved = [];
 globalThis.chrome = {
  storage: {local: {async get() { return {preferences}; }, async set(value) { saved.push(value.preferences); }},
   session: {async get() { return {}; }}},
  tabs: {async query() { return [{id: 7, title: 'Video', url}]; }},
  runtime: {async sendMessage(message) {
   messages.push(message);
   return message.action === 'inspect' ? {position: 42} : await playResponse;
  }},
 };
 await import(`../extension/popup.js?test=${++popupCount}`);
 await new Promise(resolve => setImmediate(resolve));
 return {elements, saved, plays: () => messages.filter(message => message.action === 'play')};
}
let popup = await openPopup();
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
popup = await openPopup({autoContinue: true}, undefined, new Promise(resolve => { finishPlay = resolve; }));
assert.equal(popup.elements.get('send').disabled, true);
await popup.elements.get('send').listeners.click();
assert.equal(popup.plays().length, 1);
finishPlay({ok: false, message: 'Could not play'});
await new Promise(resolve => setImmediate(resolve));
assert.equal(popup.elements.get('status').textContent, 'Could not play');
assert.equal(popup.elements.get('send').disabled, false);
popup.elements.get('autoContinue').checked = false;
await popup.elements.get('autoContinue').listeners.change();
popup = await openPopup(popup.saved[0]);
assert.equal(popup.plays().length, 0);
console.log('Frame Ferry: settings, identity, timestamps, readiness, pause, navigation, duplicate requests, capture and popup passed.');
