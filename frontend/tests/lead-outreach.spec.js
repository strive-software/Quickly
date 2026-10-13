import { test, expect } from '@playwright/test';

async function mock(page) {
  const writes = [];
  const slots = {};
  const lead = { id: 1, name: 'Alex', email: 'alex@example.com', priority: 'normal', apollo_id: '', notes: '', campaigns: [], custom_data: {}, interactions: [], linkedin_messages: [] };
  await page.route('**/api/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    let data = {
      '/api/auth/setup-status': { setup_complete: true },
      '/api/auth/refresh': { access_token: 'local-test-only' },
      '/api/auth/me': { id: 1, email: 'test@example.com', role: 'admin', name: 'Test' },
      '/api/status': { app_mode: 'production', test_mode: true },
      '/api/leads/1': lead,
      '/api/leads': [lead],
      '/api/inboxes': [{ id: 1, email: 'sender@example.com' }],
      '/api/campaigns/1': { id: 1, name: 'Outreach', paused: true, inbox_ids: [1], timezone: 'UTC', llm_voice: 'Sequence rules' },
      '/api/campaigns/1/sequences': [],
      '/api/campaigns/1/leads': [],
      '/api/campaigns/1/analytics/steps': [],
      '/api/settings/llm-voice': { company_voice: 'Company rules' },
    }[path] ?? {};
    if (['PATCH', 'PUT'].includes(request.method())) {
      const body = request.postDataJSON(); writes.push({ path, body });
      if (path.includes('/linkedin/')) {
        data = { message: '', sent: false, ...slots[path], ...body };
        data.sent_at = data.sent ? (data.sent_at || '2026-10-13T12:00:00Z') : null;
        slots[path] = data;
      } else data = { ...data, ...body };
    }
    await route.fulfill({ json: data });
  });
  return writes;
}
async function visit(page, path) {
  await page.goto(path);
  await page.getByRole('button', { name: 'Skip onboarding' }).click();
}

test('profile saves Apollo ID and notes, message sent can be undone independently', async ({ page }) => {
  const writes = await mock(page);
  await visit(page, '/leads/1');
  await page.getByLabel('Apollo ID').fill('apollo-123');
  await page.getByLabel('Job title', { exact: true }).fill('VP Operations');
  await page.getByLabel('Notes', { exact: true }).fill('Met in person');
  await page.getByRole('button', { name: 'Save profile & notes' }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0].body).not.toHaveProperty('linkedin_paused');
  expect(writes[0].body).not.toHaveProperty('linkedin_replied_at');
  expect(writes[0].body).toMatchObject({ apollo_id: 'apollo-123', job_title: 'VP Operations', notes: 'Met in person' });
  await page.getByLabel('LinkedIn message 2 (optional)').fill('Following up');
  const form = page.getByRole('button', { name: 'Save message 2' }).locator('..');
  await form.getByLabel('Message sent', { exact: true }).check();
  await form.getByRole('button').click();
  await expect.poll(() => writes.length).toBe(2);
  expect(writes[1]).toEqual({ path: '/api/leads/1/linkedin/2', body: { message: 'Following up', sent: true } });
  await page.getByLabel('LinkedIn message 2 (optional)').fill('Following up again');
  await form.getByRole('button').click();
  await expect.poll(() => writes.length).toBe(3);
  expect(writes[2].body).not.toHaveProperty('sent_at');
  await form.getByLabel('Message sent', { exact: true }).uncheck();
  await form.getByRole('button').click();
  await expect.poll(() => writes.length).toBe(4);
  expect(writes[3].body.sent).toBe(false);
});

test('global and sequence voice are editable in their settings', async ({ page }) => {
  const writes = await mock(page);
  await visit(page, '/settings');
  await page.getByRole('textbox', { name: 'LLM Company Voice', exact: true }).fill('Be direct');
  await page.getByRole('button', { name: 'Save company voice' }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]).toEqual({ path: '/api/settings/llm-voice', body: { company_voice: 'Be direct' } });
  await page.goto('/campaigns/1#settings');
  await page.getByRole('textbox', { name: /^Sequence LLM Voice/ }).fill('Focus on operations');
  await page.getByRole('button', { name: 'Save settings', exact: true }).click();
  await expect.poll(() => writes.some(w => w.body.llm_voice === 'Focus on operations')).toBe(true);
});
