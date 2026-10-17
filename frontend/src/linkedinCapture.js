import { api } from './api';

export const CAPTURE_CONTEXT_KEY = 'quickly.linkedinCaptureLead';
export const CAPTURE_REQUEST_EVENT = 'quickly:linkedin-capture';
export const CAPTURE_RESULT_EVENT = 'quickly:linkedin-capture-result';
const MAX_AGE_MS = 30 * 60 * 1000;

export function rememberLinkedInLead(leadId, profileUrl) {
  if (!Number.isInteger(Number(leadId)) || Number(leadId) <= 0) return;
  try {
    const url = new URL(profileUrl);
    if (url.protocol !== 'https:' || !/(^|\.)linkedin\.com$/.test(url.hostname) ||
        !url.pathname.startsWith('/in/')) return;
    localStorage.setItem(CAPTURE_CONTEXT_KEY, JSON.stringify({
      leadId: Number(leadId), profile: url.pathname.replace(/\/$/, ''), at: Date.now(),
    }));
  } catch { /* Ignore malformed profile links. */ }
}

export function captureLeadContext(value, now = Date.now()) {
  try {
    const context = JSON.parse(value);
    if (!Number.isInteger(context.leadId) || context.leadId <= 0 ||
        typeof context.profile !== 'string' || !context.profile.startsWith('/in/') ||
        !Number.isFinite(context.at) || now - context.at < 0 || now - context.at > MAX_AGE_MS) return null;
    return context;
  } catch { return null; }
}

export function validCapture(capture, context) {
  if (!capture || typeof capture !== 'object' || !context) return false;
  try {
    const url = new URL(capture.url);
    const profile = context.profile.toLowerCase();
    const path = url.pathname.replace(/\/$/, '').toLowerCase();
    return capture.url.length <= 2048 && url.protocol === 'https:' && /(^|\.)linkedin\.com$/.test(url.hostname) &&
      (path === profile || path.startsWith(profile + '/')) &&
      typeof capture.text === 'string' && capture.text.trim().length > 0 &&
      capture.text.length <= 9500;
  } catch { return false; }
}

export async function saveLinkedInCapture(leadId, capture) {
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const current = await api.get(`/leads/${leadId}/research`);
    const source = {
      url: new URL(capture.url).origin + new URL(capture.url).pathname.replace(/\/$/, ''),
      title: `LinkedIn capture · ${String(capture.title || 'Profile').slice(0, 480)}`,
      notes: capture.text.trim(),
    };
    const sources = [...(current.sources || [])];
    // Preserve manually edited research; each capture is a separate source.
    sources.push(source);
    try {
      return await api.put(`/leads/${leadId}/research`, {
        summary: current.summary || '', sources, expected_updated_at: current.updated_at || null,
      });
    } catch (error) {
      if (error.status !== 409 || attempt === 1) throw error;
    }
  }
}
