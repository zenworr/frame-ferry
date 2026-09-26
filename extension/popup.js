// SPDX-License-Identifier: MIT
import {settings, sameVideo} from './settings.js';
const $ = id => document.getElementById(id);
let preferences, tab, captured, busy = false, pending = false, allowed = false;
function report(message, error = false) {
  $('status').textContent = message;
  $('status').classList.toggle('error', error);
}
function labels() {
  const resumeLabel = captured ? 'Continue in mpv ↗' : 'Open in mpv ↗';
  $('send').textContent = preferences.resume ? resumeLabel : 'Play from the beginning ↗';
  $('alternate').textContent = preferences.resume ? 'Play from the beginning' : resumeLabel;
}
function buttons() {
  $('send').disabled = $('alternate').disabled = !allowed || busy || pending;
}
function showStatus(state) {
  pending = !!state?.pending;
  buttons();
  if (state && sameVideo(state.page, tab.url)) report(state.text, state.error);
  else report(pending ? 'A handoff from this tab is still in progress.' : '');
}
async function send(resume) {
  if (busy || pending || !allowed) return;
  busy = true;
  buttons();
  report('Opening mpv… The browser keeps playing until mpv is ready.');
  try {
    const response = await chrome.runtime.sendMessage({action: 'play', tabId: tab.id, resume, quality: Number($('quality').value)});
    report(response.message, !response.ok);
  } catch (error) { report(error.message, true); }
  finally { busy = false; buttons(); }
}
async function init() {
  preferences = await settings();
  for (const key of ['resume', 'pause', 'fullscreen', 'autoContinue']) $(key).checked = preferences[key];
  $('quality').value = $('default-quality').value = String(preferences.quality);
  for (const key of ['resume', 'pause', 'fullscreen', 'autoContinue', 'default-quality']) {
    $(key).addEventListener('change', async () => {
      preferences = {resume: $('resume').checked, pause: $('pause').checked,
        fullscreen: $('fullscreen').checked, autoContinue: $('autoContinue').checked,
        quality: Number($('default-quality').value)};
      await chrome.storage.local.set({preferences});
      labels();
      if (!busy && !pending) report('Defaults saved on this device.');
    });
  }
  $('send').addEventListener('click', () => send(preferences.resume));
  $('alternate').addEventListener('click', () => send(!preferences.resume));
  $('check').addEventListener('click', async () => {
    try {
      const response = await chrome.runtime.sendMessage({action: 'check'});
      report(response.message, !response.ok);
    } catch (error) { report(error.message, true); }
  });
  [tab] = await chrome.tabs.query({active: true, currentWindow: true});
  $('page-title').textContent = tab?.title || tab?.url || 'No active page';
  allowed = /^https?:\/\//i.test(tab?.url || '');
  captured = allowed ? await chrome.runtime.sendMessage({action: 'inspect', tabId: tab.id}) : null;
  $('position').textContent = captured
    ? `At ${Math.floor(captured.position / 60)}:${String(captured.position % 60).padStart(2, '0')} · captured again when you click`
    : 'No recorded-video position found. Open uses the URL or saved position.';
  labels();
  buttons();
  if (!allowed) report('Open an HTTP or HTTPS video page to use Frame Ferry.', true);
  else {
    const key = 'status:' + tab.id;
    let updated = false;
    chrome.storage.onChanged.addListener((changes, area) => {
      if (area !== 'session' || !changes[key]) return;
      updated = true;
      showStatus(changes[key].newValue);
    });
    const last = (await chrome.storage.session.get(key))[key];
    if (!updated) showStatus(last);
    if (preferences.autoContinue && !pending) await send(true);
  }
}
init().catch(error => report(error.message, true));
