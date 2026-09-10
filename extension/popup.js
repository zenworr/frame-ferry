// SPDX-License-Identifier: MIT
import {settings} from './settings.js';
const $ = id => document.getElementById(id);
let preferences, tab, captured, busy = false;
function report(message, error = false) {
  $('status').textContent = message;
  $('status').classList.toggle('error', error);
}
function labels() {
  const resumeLabel = captured ? 'Continue in mpv ↗' : 'Open in mpv ↗';
  $('send').textContent = preferences.resume ? resumeLabel : 'Play from the beginning ↗';
  $('alternate').textContent = preferences.resume ? 'Play from the beginning' : resumeLabel;
}
async function send(resume) {
  if (busy) return;
  busy = true;
  $('send').disabled = $('alternate').disabled = true;
  report('Opening mpv… The browser keeps playing until mpv is ready.');
  try {
    const response = await chrome.runtime.sendMessage({action: 'play', tabId: tab.id, resume, quality: Number($('quality').value)});
    report(response.message, !response.ok);
  } catch (error) { report(error.message, true); }
  finally { busy = false; $('send').disabled = $('alternate').disabled = false; }
}
async function init() {
  preferences = await settings();
  for (const key of ['resume', 'pause', 'fullscreen']) $(key).checked = preferences[key];
  $('quality').value = $('default-quality').value = String(preferences.quality);
  for (const key of ['resume', 'pause', 'fullscreen', 'default-quality']) {
    $(key).addEventListener('change', async () => {
      preferences = {resume: $('resume').checked, pause: $('pause').checked,
        fullscreen: $('fullscreen').checked, quality: Number($('default-quality').value)};
      await chrome.storage.local.set({preferences});
      labels();
      if (!busy) report('Defaults saved on this device.');
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
  const allowed = /^https?:\/\//i.test(tab?.url || '');
  captured = allowed ? await chrome.runtime.sendMessage({action: 'inspect', tabId: tab.id}) : null;
  $('position').textContent = captured
    ? `At ${Math.floor(captured.position / 60)}:${String(captured.position % 60).padStart(2, '0')} · captured again when you click`
    : 'No recorded-video position found. Open uses the URL or saved position.';
  labels();
  $('send').disabled = $('alternate').disabled = !allowed;
  if (!allowed) report('Open an HTTP or HTTPS video page to use Frame Ferry.', true);
  else {
    const last = (await chrome.storage.session.get('status:' + tab.id))['status:' + tab.id];
    if (last) report(last.text, last.error);
  }
}
init().catch(error => report(error.message, true));
