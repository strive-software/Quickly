const MAX_TEXT = 9500;
const preview = document.getElementById('preview');
const status = document.getElementById('status');
const count = document.getElementById('count');
const saveButton = document.getElementById('save');
const tabSelect = document.getElementById('crm-tab');
let linkedinTab;
let captured;
let crmTabs = new Map();

function show(message, error = false) {
  status.textContent = message;
  status.className = error ? 'error' : '';
}

function linkedinUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && /(^|\.)linkedin\.com$/.test(url.hostname);
  } catch { return false; }
}

function captureFromPage(mode) {
  const selected = window.getSelection()?.toString().trim() || '';
  const root = document.querySelector('main') || document.body;
  const text = mode === 'selection' ? selected : root?.innerText?.trim() || '';
  return { url: location.href, title: document.title, text: text.slice(0, 9500) };
}

async function capture(mode) {
  try {
    if (!linkedinTab || !linkedinUrl(linkedinTab.url)) throw new Error('Open a LinkedIn page first.');
    const [result] = await chrome.scripting.executeScript({
      target: { tabId: linkedinTab.id }, func: captureFromPage, args: [mode],
    });
    captured = result.result;
    if (!captured.text) throw new Error(mode === 'selection' ? 'Select text on the page first.' : 'No visible text was found.');
    preview.value = captured.text;
    count.textContent = `${captured.text.length}/${MAX_TEXT}`;
    saveButton.disabled = false;
    show('Review the text, then save it to the lead.');
  } catch (error) {
    captured = null;
    saveButton.disabled = true;
    show(error.message || 'Capture failed.', true);
  }
}

async function refreshTabs() {
  const [active] = await chrome.tabs.query({ active: true, currentWindow: true });
  linkedinTab = active;
  const tabs = await chrome.tabs.query({});
  crmTabs = new Map(tabs.filter(tab => {
    try {
      const url = new URL(tab.url);
      return ['http:', 'https:'].includes(url.protocol) && !linkedinUrl(tab.url) &&
        (url.pathname.startsWith('/leads') || url.pathname.startsWith('/campaigns'));
    } catch { return false; }
  }).map(tab => [String(tab.id), tab]));
  tabSelect.replaceChildren();
  for (const [id, tab] of crmTabs) {
    const option = document.createElement('option');
    option.value = id;
    option.textContent = `${tab.title || 'CRM tab'} · ${new URL(tab.url).host}`;
    tabSelect.append(option);
  }
  if (!crmTabs.size) show('Keep the Quickly lead or campaign tab open, then reopen this extension.', true);
}

function deliverToCrm(nonce, capture) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      window.removeEventListener('quickly:linkedin-capture-result', onResult);
      reject(new Error('The selected tab did not respond. Refresh Quickly and try again.'));
    }, 15000);
    function onResult(event) {
      if (event.detail?.nonce !== nonce) return;
      clearTimeout(timer);
      window.removeEventListener('quickly:linkedin-capture-result', onResult);
      resolve(event.detail);
    }
    window.addEventListener('quickly:linkedin-capture-result', onResult);
    window.dispatchEvent(new CustomEvent('quickly:linkedin-capture', { detail: { nonce, capture } }));
  });
}

async function save() {
  try {
    const tab = crmTabs.get(tabSelect.value);
    if (!tab) throw new Error('Choose the open Quickly tab.');
    if (!captured) throw new Error('Capture the LinkedIn page first.');
    const text = preview.value.trim();
    if (!text || text.length > MAX_TEXT) throw new Error(`Text must be between 1 and ${MAX_TEXT} characters.`);
    const crmUrl = new URL(tab.url);
    // Chrome host-permission patterns cannot contain a port.
    const hostPattern = `${crmUrl.protocol}//${crmUrl.hostname}/*`;
    saveButton.disabled = true;
    show('Saving to Quickly…');
    const allowed = await chrome.permissions.request({ origins: [hostPattern] });
    if (!allowed) throw new Error('Allow access to the Quickly tab to save this research.');
    const nonce = [...crypto.getRandomValues(new Uint8Array(16))].map(n => n.toString(16).padStart(2, '0')).join('');
    const [result] = await chrome.scripting.executeScript({
      target: { tabId: tab.id }, func: deliverToCrm,
      args: [nonce, { ...captured, text }], world: 'MAIN',
    });
    if (!result.result?.ok) throw new Error(result.result?.message || 'Quickly could not save the research.');
    show(`${result.result.message} Lead #${result.result.leadId}.`);
  } catch (error) {
    show(error.message || 'Could not save research.', true);
  } finally {
    saveButton.disabled = !captured;
  }
}

document.getElementById('capture-selection').addEventListener('click', () => capture('selection'));
document.getElementById('capture-page').addEventListener('click', () => capture('page'));
preview.addEventListener('input', () => {
  count.textContent = `${preview.value.length}/${MAX_TEXT}`;
  saveButton.disabled = !captured || !preview.value.trim() || preview.value.length > MAX_TEXT;
});
saveButton.addEventListener('click', save);
refreshTabs().catch(error => show(error.message || 'Could not find tabs.', true));
