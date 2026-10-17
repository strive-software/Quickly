import { test, expect } from '@playwright/test';

test('a CRM-linked manual capture saves text to the matching lead without replacing the summary', async ({ page }) => {
  const writes = [];
  const lead = { id: 7, email: 'alex@example.com', name: 'Alex', linkedin_url: 'https://www.linkedin.com/in/alex/',
    job_title: 'VP Operations', company: 'Acme', priority: 'normal', campaigns: [], interactions: [] };
  const research = { lead_id: 7, summary: 'Keep this summary', sources: [], updated_at: '2026-10-15T12:00:00Z' };
  await page.route('**/api/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === 'PUT' && path === '/api/leads/7/research') {
      writes.push(request.postDataJSON());
      await route.fulfill({ json: { ...research, ...request.postDataJSON() } });
      return;
    }
    const data = {
      '/api/auth/setup-status': { setup_complete: true }, '/api/auth/refresh': { access_token: 'test' },
      '/api/auth/me': { id: 1, email: 'owner@example.com', role: 'admin', name: 'Owner' },
      '/api/status': { app_mode: 'production', test_mode: true },
      '/api/leads': [lead], '/api/leads/7': lead, '/api/leads/7/research': research,
      '/api/leads/7/emails': { items: [] },
    }[path] ?? {};
    await route.fulfill({ json: data });
  });
  await page.goto('/leads');
  await page.getByRole('button', { name: 'Skip onboarding' }).click();
  await page.evaluate(() => document.addEventListener('click', event => event.preventDefault(), { capture: true, once: true }));
  await page.getByRole('link', { name: 'Alex' }).click();
  const context = await page.evaluate(() => JSON.parse(localStorage.getItem('quickly.linkedinCaptureLead')));
  expect(context.leadId).toBe(7);

  async function sendCapture(url) {
    return page.evaluate(url => new Promise(resolve => {
      const nonce = 'a'.repeat(32);
      const onResult = event => {
        if (event.detail?.nonce !== nonce || event.detail?.stage === 'received') return;
        window.removeEventListener('quickly:linkedin-capture-result', onResult);
        resolve(event.detail);
      };
      window.addEventListener('quickly:linkedin-capture-result', onResult);
      window.dispatchEvent(new CustomEvent('quickly:linkedin-capture', {
        detail: { nonce, capture: { url, title: 'Alex | LinkedIn', text: 'VP Operations at Acme' } },
      }));
    }), url);
  }

  expect((await sendCapture('https://www.linkedin.com/in/other/')).ok).toBe(false);
  expect(writes).toHaveLength(0);
  expect((await sendCapture('https://www.linkedin.com/in/alex/')).ok).toBe(true);
  expect(writes).toHaveLength(1);
  expect(writes[0].summary).toBe('Keep this summary');
  expect(writes[0].sources[0]).toMatchObject({
    url: 'https://www.linkedin.com/in/alex', notes: 'VP Operations at Acme',
  });
});
