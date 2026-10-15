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

test('profile saves Apollo ID and notes without lead-level LinkedIn messages', async ({ page }) => {
  const writes = await mock(page);
  await visit(page, '/leads/1');
  await page.getByLabel('Apollo ID').fill('apollo-123');
  await page.getByLabel('Job title', { exact: true }).fill('VP Operations');
  await page.getByLabel('Company', { exact: true }).fill('Acme');
  await page.getByLabel('Notes', { exact: true }).fill('Met in person');
  await page.getByRole('button', { name: 'Save profile & notes' }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0].body).not.toHaveProperty('linkedin_paused');
  expect(writes[0].body).not.toHaveProperty('linkedin_replied_at');
  expect(writes[0].body).toMatchObject({ apollo_id: 'apollo-123', job_title: 'VP Operations', company: 'Acme', notes: 'Met in person' });
  await expect(page.getByText('Pause LinkedIn outreach')).toHaveCount(0);
  await expect(page.getByRole('button', { name: /Save message/ })).toHaveCount(0);
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

test('campaign manual step supports pending/done, dates and independent ignore', async ({ page }) => {
  await mock(page);
  const writes = [];
  let record = { campaign_lead_id: 11, lead_id: 1, name: 'Alex', email: 'alex@example.com', priority: 'high', sequence_id: 3, position: 1, message: 'Hello Alex', sent: false, sent_at: null, ignored: false, ready: true, mode: 'hold' };
  await page.route('**/api/campaigns/1/sequences', route => route.fulfill({ json: [{ id: 3, position: 1, sequence_type: 'linkedin', manual_mode: 'hold', body: '', wait_days_after_previous: 0 }] }));
  await page.route('**/api/campaigns/1/manual-steps?*', route => route.fulfill({ json: [record] }));
  await page.route('**/api/campaigns/1/leads/1/manual-steps/3', route => {
    const body = route.request().postDataJSON(); writes.push(body);
    record = { ...record, ...body };
    record.sent_at = record.sent ? record.sent_at || '2026-10-13T12:00:35Z' : null;
    return route.fulfill({ json: record });
  });
  await visit(page, '/campaigns/1#sequences');
  const form = page.getByRole('form', { name: 'LinkedIn for alex@example.com' });
  await expect(form.getByText('Pending · Ready — waiting for manual completion')).toBeVisible();
  await form.getByRole('textbox', { name: 'Message', exact: true }).fill('Personal follow up');
  await form.getByRole('combobox', { name: 'Status', exact: true }).selectOption('done');
  await form.getByLabel('Ignore for this lead').check();
  await form.getByRole('button', { name: 'Save manual step' }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]).toMatchObject({ message: 'Personal follow up', sent: true, ignored: true });
  await expect(form.getByRole('button', { name: 'Save manual step' })).toBeEnabled();
  await expect(form.getByLabel(/^Sent at/)).not.toBeEmpty();
  await expect(form.getByText('Done · Ignored')).toBeVisible();
  await form.getByRole('textbox', { name: 'Message', exact: true }).fill('Updated text');
  await form.getByRole('button', { name: 'Save manual step' }).click();
  await expect.poll(() => writes.length).toBe(2);
  expect(writes[1]).toEqual({ message: 'Updated text' });
  await expect(form.getByRole('button', { name: 'Save manual step' })).toBeEnabled();
  await form.getByRole('combobox', { name: 'Status', exact: true }).selectOption('pending');
  await form.getByRole('button', { name: 'Save manual step' }).click();
  await expect.poll(() => writes.length).toBe(3);
  expect(writes[2]).toEqual({ sent: false });
  await expect(form.getByLabel('Ignore for this lead')).toBeChecked();
  await expect(form.getByText('Pending · Ignored')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Preview', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Add Step', exact: true }).click();
  await page.getByLabel('Sequence type').selectOption('linkedin');
  await expect(page.getByRole('combobox', { name: 'Manual step behavior', exact: true })).toHaveValue('hold');
  await page.getByRole('combobox', { name: 'Manual step behavior', exact: true }).selectOption('ignore');
  await expect(page.getByLabel('LinkedIn draft (optional)')).toBeVisible();
  await expect(page.getByText('Email Body *', { exact: true })).toHaveCount(0);
});

test('editing manual draft sends only content and keeps type fixed', async ({ page }) => {
  await mock(page);
  const writes = [];
  const sequence = { id: 3, position: 0, sequence_type: 'linkedin', manual_mode: 'ignore', body: 'Initial draft', wait_days_after_previous: 9 };
  await page.route('**/api/campaigns/1/sequences', route => route.fulfill({ json: [sequence] }));
  await page.route('**/api/campaigns/1/sequences/3', route => {
    const body = route.request().postDataJSON(); writes.push(body);
    return route.fulfill({ json: { ...sequence, ...body } });
  });
  await page.route('**/api/campaigns/1/manual-steps?*', route => route.fulfill({ json: [{ campaign_lead_id: 11, lead_id: 1, email: 'alex@example.com', sequence_id: 3, message: 'Draft', sent: false, ignored: false, ready: true, mode: 'ignore' }] }));
  await visit(page, '/campaigns/1#sequences');
  await expect(page.getByText('Pending · Does not hold email')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Manual LinkedIn Day 0' })).toBeVisible();
  await page.getByRole('button', { name: 'Edit', exact: true }).click();
  await expect(page.getByLabel('Sequence type').locator('option')).toHaveCount(1);
  await page.getByRole('textbox', { name: 'LinkedIn draft (optional)' }).fill('Revised draft');
  await page.getByRole('button', { name: 'Save Changes', exact: true }).click();
  await expect.poll(() => writes).toEqual([{ body: 'Revised draft' }]);
});

for (const linkedinUrl of ['https://www.linkedin.com/in/alex', '', 'https://linkedin.com.evil.example/in/alex']) {
  test(`lead name links only to LinkedIn: ${linkedinUrl || 'missing profile'}`, async ({ page }) => {
    await mock(page);
    const lead = { id: 1, lead_id: 1, name: 'Alex', email: 'alex@example.com', linkedin_url: linkedinUrl, campaigns: [], interactions: [], custom_data: {} };
    await page.route('**/api/leads/1', route => route.fulfill({ json: lead }));
    await page.route('**/api/campaigns/1/leads', route => route.fulfill({ json: [lead] }));
    await visit(page, '/campaigns/1#leads');
    for (const path of ['/campaigns/1#leads', '/leads/1']) {
      await page.goto(path);
      const name = page.getByRole('link', { name: 'Alex', exact: true });
      if (linkedinUrl === 'https://www.linkedin.com/in/alex') {
        await expect(name).toHaveAttribute('href', linkedinUrl);
        await expect(name).toHaveAttribute('target', '_blank');
        await expect(name).toHaveAttribute('rel', 'noopener noreferrer');
      } else {
        await expect(page.getByText('Alex', { exact: true }).first()).toBeVisible();
        await expect(name).toHaveCount(0);
      }
    }
  });
}
