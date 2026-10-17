const MAX_TEXT = 9500;
const preview = document.getElementById('preview');
const status = document.getElementById('status');
const count = document.getElementById('count');
const saveButton = document.getElementById('save');
const tabSelect = document.getElementById('crm-tab');
let linkedinTab;
let captured;
let crmTabs = new Map();
let crmOrigin;

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

function localHttpHost(hostname) {
  if (['localhost', '127.0.0.1', '[::1]'].includes(hostname)) return true;
  const octets = hostname.split('.').map(Number);
  return octets.length === 4 && octets.every(n => Number.isInteger(n) && n >= 0 && n <= 255) &&
    (octets[0] === 10 || (octets[0] === 192 && octets[1] === 168) ||
      (octets[0] === 172 && octets[1] >= 16 && octets[1] <= 31));
}

function captureFromPage(mode, maxText) {
  const selected = window.getSelection()?.toString().trim() || '';
  const root = document.querySelector('main') || document.body;
  const text = mode === 'selection' ? selected : root?.innerText?.trim() || '';
  let clipped = text.slice(0, maxText);
  if (/[\uD800-\uDBFF]$/.test(clipped)) clipped = clipped.slice(0, -1);
  return { url: location.origin + location.pathname, title: document.title,
    text: clipped, truncated: text.length > maxText };
}

async function capture(mode) {
  try {
    if (!linkedinTab || !linkedinUrl(linkedinTab.url)) throw new Error('Open a LinkedIn page first.');
    const [result] = await chrome.scripting.executeScript({
      target: { tabId: linkedinTab.id }, func: captureFromPage, args: [mode, MAX_TEXT],
    });
    captured = result.result;
    if (!captured.text) throw new Error(mode === 'selection' ? 'Select text on the page first.' : 'No visible text was found.');
    preview.value = captured.text;
    count.textContent = `${captured.text.length}/${MAX_TEXT}`;
    saveButton.disabled = false;
    show(captured.truncated ? 'Truncated to 9,500 characters. Review before saving.' : 'Review the text, then save it to the lead.');
  } catch (error) {
    captured = null;
    saveButton.disabled = true;
    show(error.message || 'Capture failed.', true);
  }
}

async function refreshTabs() {
  const [active] = await chrome.tabs.query({ active: true, currentWindow: true });
  linkedinTab = active;
  crmOrigin = (await chrome.storage.local.get('crmOrigin')).crmOrigin;
  document.getElementById('connect').hidden = linkedinUrl(active?.url);
  document.getElementById('connected').textContent = crmOrigin ? `Quickly: ${crmOrigin}` : 'First open Quickly and connect its tab.';
  const tabs = await chrome.tabs.query({});
  crmTabs = new Map(tabs.filter(tab => {
    try {
      const url = new URL(tab.url);
      return url.origin === crmOrigin &&
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
  if (!crmTabs.size && linkedinUrl(active?.url)) show('Keep the connected Quickly lead or campaign tab open.', true);
}

async function connectCurrentTab() {
  try {
    const url = new URL(linkedinTab.url);
    if (!['http:', 'https:'].includes(url.protocol) || linkedinUrl(url.href) ||
        !linkedinTab.title?.includes('Quickly')) throw new Error('Open Quickly first.');
    if (url.protocol === 'http:' && !localHttpHost(url.hostname)) {
      throw new Error('Quickly must use HTTPS, except on localhost or a private LAN.');
    }
    const allowed = await chrome.permissions.request({ origins: [`${url.origin}/*`] });
    if (!allowed) throw new Error('Chrome did not grant access to this CRM tab.');
    await chrome.storage.local.set({ crmOrigin: url.origin });
    await refreshTabs();
    show('Connected. Open a lead’s LinkedIn profile from this CRM.');
  } catch (error) { show(error.message || 'Could not connect this tab.', true); }
}

function deliverToCrm(nonce, capture) {
  return new Promise((resolve, reject) => {
    const fail = message => {
      clearTimeout(ackTimer);
      clearTimeout(completionTimer);
      window.removeEventListener('quickly:linkedin-capture-result', onResult);
      reject(new Error(message));
    };
    const ackTimer = setTimeout(() => fail('Quickly did not respond. Refresh and sign in, then try again.'), 5000);
    const completionTimer = setTimeout(() => fail('Saving is taking too long. Check the lead’s research before retrying.'), 120000);
    function onResult(event) {
      if (event.detail?.nonce !== nonce) return;
      if (event.detail.stage === 'received') {
        clearTimeout(ackTimer);
        return;
      }
      clearTimeout(ackTimer);
      clearTimeout(completionTimer);
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
    saveButton.disabled = true;
    show('Saving to Quickly…');
    const nonce = [...crypto.getRandomValues(new Uint8Array(16))].map(n => n.toString(16).padStart(2, '0')).join('');
    const [result] = await chrome.scripting.executeScript({
      target: { tabId: tab.id }, func: deliverToCrm,
      args: [nonce, { ...captured, text }], world: 'MAIN',
    });
    if (!result.result?.ok) throw new Error(result.result?.message || 'Quickly could not save the research.');
    captured = null;
    show(`${result.result.message} Lead #${result.result.leadId}. Open the link again for another capture.`);
  } catch (error) {
    show(error.message || 'Could not save research.', true);
  } finally {
    saveButton.disabled = !captured;
  }
}

document.getElementById('capture-selection').addEventListener('click', () => capture('selection'));
document.getElementById('capture-page').addEventListener('click', () => capture('page'));
document.getElementById('connect').addEventListener('click', connectCurrentTab);
preview.addEventListener('input', () => {
  count.textContent = `${preview.value.length}/${MAX_TEXT}`;
  saveButton.disabled = !captured || !preview.value.trim() || preview.value.length > MAX_TEXT;
});
saveButton.addEventListener('click', save);
refreshTabs().catch(error => show(error.message || 'Could not find tabs.', true));
