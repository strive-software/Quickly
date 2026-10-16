import { test, expect } from '@playwright/test';

test('lead details keep research sources and save a personalized draft without releasing it', async ({ page }) => {
  const writes = [];
  const lead = { id: 7, email: 'alex@example.com', name: 'Alex', job_title: 'VP Operations', company: 'Acme', priority: 'normal', email_verification_status: 'valid', campaigns: [], interactions: [] };
  let research = { lead_id: 7, summary: 'Operations leader', sources: [{ title: 'Profile', url: 'https://www.linkedin.com/in/alex', notes: 'Current role' }], updated_at: '2026-10-15T12:00:00Z' };
  const email = { kind: 'pending', status: 'needs_writing', campaign_id: 3, campaign_name: 'Outreach', sequence_id: 11, sequence_index: 1, subject: 'Hello Alex', body: 'Draft body', is_html: false, editing_source: { subject: 'Hello {{name}}', body: 'Draft {{name}}', is_html: false }, from_email: 'sender@example.com', to_email: 'alex@example.com', scheduled_at: null, editable: true, draft: null };
  await page.route('**/api/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    let data = {
      '/api/auth/setup-status': { setup_complete: true }, '/api/auth/refresh': { access_token: 'test' },
      '/api/auth/me': { id: 1, email: 'owner@example.com', role: 'admin', name: 'Owner' },
      '/api/status': { app_mode: 'production', test_mode: true },
      '/api/leads': [lead], '/api/leads/7': lead, '/api/leads/7/research': research,
      '/api/leads/7/emails': { items: [email] },
    }[path] ?? {};
    if (request.method() === 'PUT' && path === '/api/leads/7/research') {
      writes.push({ path, body: request.postDataJSON() });
      research = { ...research, ...request.postDataJSON(), updated_at: '2026-10-16T12:00:00Z' };
      data = research;
    }
    if (request.method() === 'PATCH' && path.endsWith('/draft')) {
      writes.push({ path, body: request.postDataJSON() });
      email.draft = { ...request.postDataJSON(), updated_at: '2026-10-16T13:00:00Z' };
      email.status = 'draft';
      data = { ok: true, draft: email.draft };
    }
    if (request.method() === 'POST' && path.endsWith('/release')) {
      writes.push({ path, body: request.postDataJSON() });
      email.status = 'scheduled';
      email.draft = null;
      data = { ok: true };
    }
    await route.fulfill({ json: data });
  });
  await page.goto('/leads');
  await page.getByRole('button', { name: 'Skip onboarding' }).click();
  await expect(page.getByRole('columnheader', { name: 'Job title' })).toBeVisible();
  await expect(page.getByRole('columnheader', { name: 'Company' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Retry verification' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Verify email' })).toHaveCount(0);
  await page.getByRole('button', { name: 'alex@example.com' }).click();
  const panel = page.getByRole('dialog', { name: 'Lead details' });
  await expect(panel.getByText('VP Operations · Acme')).toBeVisible();
  await expect(panel.getByRole('button', { name: 'Close lead details' })).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await expect(panel.getByRole('button', { name: 'Save profile & notes' })).toBeFocused();
  await page.screenshot({ path: 'test-results/lead-crm-panel.png' });
  await panel.getByRole('button', { name: 'Research' }).click();
  await expect(panel.getByText('Last updated')).toBeVisible();
  await panel.getByLabel('Research summary').fill('New research');
  await panel.getByRole('button', { name: 'Save research' }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0].body).toMatchObject({ expected_updated_at: '2026-10-15T12:00:00Z', sources: [{ url: 'https://www.linkedin.com/in/alex' }] });
  await panel.getByRole('button', { name: 'Emails' }).click();
  await expect(panel.getByText('Needs writing')).toBeVisible();
  await expect(panel.getByText('Outreach · Step 2')).toBeVisible();
  await panel.getByRole('button', { name: 'Preview' }).click();
  await expect(panel.getByText('sender@example.com')).toHaveCount(2);
  await panel.getByRole('button', { name: 'Close email preview' }).click();
  await panel.getByRole('button', { name: 'Edit this lead’s email' }).click();
  await expect(panel.getByRole('textbox', { name: 'Subject' })).toHaveValue('Hello {{name}}');
  await expect(panel.getByRole('textbox', { name: 'Body' })).toHaveValue('Draft {{name}}');
  await panel.getByRole('textbox', { name: 'Body' }).fill('Only Alex gets this wording');
  await panel.getByRole('button', { name: 'Save draft' }).click();
  await expect.poll(() => writes.length).toBe(2);
  expect(writes[1]).toEqual({ path: '/api/campaigns/3/leads/7/custom-email/11/draft', body: { subject: 'Hello {{name}}', body: 'Only Alex gets this wording', is_html: false, expected_updated_at: null } });
  await expect(panel.getByText('Draft saved. Sending schedule was not activated.')).toBeVisible();
  await expect(panel.getByRole('button', { name: 'Release draft for scheduling' })).toBeVisible();
  expect(writes).toHaveLength(2);
  await panel.getByRole('button', { name: 'Release draft for scheduling' }).click();
  await expect.poll(() => writes.length).toBe(3);
  expect(writes[2]).toEqual({ path: '/api/campaigns/3/leads/7/custom-email/11/release', body: { expected_updated_at: '2026-10-16T13:00:00Z' } });
  await page.keyboard.press('Escape');
  await expect(page.getByRole('button', { name: 'alex@example.com' })).toBeFocused();
});

test('campaign leads table shows row number and profile, and opens the same lead sections', async ({ page }) => {
  const lead = { id: 7, email: 'alex@example.com', name: 'Alex', job_title: 'VP Operations', company: 'Acme', priority: 'normal', campaigns: [], interactions: [] };
  const writes = [];
  await page.route('**/api/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const data = {
      '/api/auth/setup-status': { setup_complete: true }, '/api/auth/refresh': { access_token: 'test' },
      '/api/auth/me': { id: 1, email: 'owner@example.com', role: 'admin', name: 'Owner' },
      '/api/status': { app_mode: 'production', test_mode: true },
      '/api/campaigns/3': { id: 3, name: 'Outreach', inbox_ids: [], timezone: 'UTC', paused: true },
      '/api/campaigns/3/leads': [{ lead_id: 7, email: lead.email, name: lead.name, job_title: lead.job_title, company: lead.company, custom_data: {}, enrolled_at: '2026-10-16T12:00:00Z', status: 'active', email_verification_status: 'verification_error', verification_error: 'Checker unavailable' }],
      '/api/campaigns/3/sequences': [], '/api/campaigns/3/queue': [], '/api/campaigns/3/sent': [],
      '/api/campaigns/3/leads/verification-status': { statuses: {} },
      '/api/settings/email-verification': { enabled: true }, '/api/inboxes': [],
      '/api/leads/7': lead,
      '/api/leads/7/research': { lead_id: 7, summary: 'Read before writing', sources: [], updated_at: null },
      '/api/leads/7/emails': { items: [
        { kind: 'pending', status: 'paused', reason: 'Campaign is paused', campaign_id: 3, campaign_name: 'Outreach', sequence_id: 4, sequence_index: 0, subject: 'Welcome', body: 'Hello', from_email: 'sender@example.com', to_email: lead.email, scheduled_at: null, editable: false },
        { kind: 'sent', status: 'sent', campaign_id: 3, campaign_name: 'Outreach', sequence_id: 5, sequence_index: 1, subject: 'Earlier note', body: '', from_email: 'sender@example.com', to_email: lead.email, sent_at: '2026-10-15T12:00:00Z', editable: false },
        { kind: 'pending', status: 'needs_writing', campaign_id: 3, campaign_name: 'Outreach', sequence_id: 6, sequence_index: 2, subject: '(reply in thread)', body: 'Hi Alex', is_html: true, editing_source: { subject: null, body: 'Hi {{name}}', is_html: null }, from_email: 'sender@example.com', to_email: lead.email, scheduled_at: null, editable: true, draft: null },
      ] },
    }[path] ?? {};
    if (request.method() === 'POST' && path === '/api/leads/7/verify') {
      writes.push({ path, body: request.postDataJSON() });
      await route.fulfill({ json: { ok: true, queued: 1, verification_status: 'pending' } });
    } else if (request.method() === 'PATCH' && path.endsWith('/draft')) {
      writes.push({ path, body: request.postDataJSON() });
      await route.fulfill({ json: { ok: true } });
    } else await route.fulfill({ json: data });
  });
  await page.goto('/campaigns/3#leads');
  await page.getByRole('button', { name: 'Skip onboarding' }).click();
  const table = page.getByRole('table').filter({ has: page.getByRole('columnheader', { name: 'Job title' }) });
  await expect(table.getByRole('row').filter({ hasText: 'alex@example.com' })).toContainText('VP Operations');
  await expect(table.getByRole('row').filter({ hasText: 'alex@example.com' })).toContainText('Acme');
  await expect(table.getByRole('row').filter({ hasText: 'alex@example.com' }).getByRole('cell').first()).toHaveText('1');
  await expect(table.getByText('Verification error: Checker unavailable')).toBeVisible();
  await table.getByRole('button', { name: 'Retry verification' }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]).toEqual({ path: '/api/leads/7/verify', body: {} });
  await table.getByRole('button', { name: 'View queue' }).click();
  await expect(page).toHaveURL(/#queue$/);
  await page.goto('/campaigns/3#leads');
  await expect(table.getByRole('button', { name: 'alex@example.com' })).toBeVisible();
  await table.getByRole('button', { name: 'alex@example.com' }).click();
  const panel = page.getByRole('dialog', { name: 'Lead details' });
  await panel.getByRole('button', { name: 'Research' }).click();
  await expect(panel.getByLabel('Research summary')).toHaveValue('Read before writing');
  await panel.getByRole('button', { name: 'Emails' }).click();
  await expect(panel.getByText('Campaign is paused')).toBeVisible();
  await expect(panel.getByText('Outreach · Step 1')).toBeVisible();
  await panel.getByRole('article').filter({ hasText: 'Earlier note' }).getByRole('button', { name: 'Preview' }).click();
  await expect(panel.getByText('Body was not saved for this historical email.')).toBeVisible();
  await page.screenshot({ path: 'test-results/lead-crm-emails.png' });
  await panel.getByRole('button', { name: 'Close email preview' }).click();
  await panel.getByRole('article').filter({ hasText: '(reply in thread)' }).getByRole('button', { name: 'Edit this lead’s email' }).click();
  await expect(panel.getByRole('textbox', { name: 'Subject' })).toHaveValue('');
  await expect(panel.getByRole('textbox', { name: 'Body' })).toHaveValue('Hi {{name}}');
  await expect(panel.getByRole('checkbox', { name: 'HTML body' })).not.toBeChecked();
  await panel.getByRole('textbox', { name: 'Body' }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: 'test-results/lead-crm-threaded-editor.png' });
  await panel.getByRole('button', { name: 'Save draft' }).click();
  await expect.poll(() => writes.length).toBe(2);
  expect(writes[1]).toEqual({ path: '/api/campaigns/3/leads/7/custom-email/6/draft', body: { subject: null, body: 'Hi {{name}}', is_html: null, expected_updated_at: null } });
});

test('unconfirmed unsubscribe requests need explicit review and rejection keeps pause', async ({ page }) => {
  const writes = [];
  const requests = [
    { kind: 'unconfirmed_unsubscribe', request_id: 31, at: '2026-10-15T12:00:00Z', last_seen_at: '2026-10-16T12:00:00Z', request_count: 2, campaign_name: 'Outreach', paused_by_request: true, review_decision: null },
    { kind: 'unconfirmed_unsubscribe', request_id: 32, at: '2026-10-15T13:00:00Z', last_seen_at: '2026-10-15T13:00:00Z', request_count: 1, campaign_name: 'Other', paused_by_request: true, review_decision: null },
    { kind: 'unconfirmed_unsubscribe', request_id: 33, at: '2026-10-15T14:00:00Z', last_seen_at: '2026-10-15T14:00:00Z', request_count: 1, campaign_name: 'Recipient campaign', paused_by_request: true, review_decision: 'confirmed' },
  ];
  await page.route('**/api/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    let data = {
      '/api/auth/setup-status': { setup_complete: true }, '/api/auth/refresh': { access_token: 'test' },
      '/api/auth/me': { id: 1, email: 'owner@example.com', role: 'admin', name: 'Owner' },
      '/api/status': { app_mode: 'production', test_mode: true },
      '/api/leads/7': { id: 7, email: 'alex@example.com', name: 'Alex', priority: 'normal', campaigns: [], custom_data: {}, interactions: requests },
    }[path] ?? {};
    if (request.method() === 'POST' && path.includes('/unconfirmed-unsubscribes/')) {
      const body = request.postDataJSON();
      const requestId = Number(path.split('/').at(-2));
      writes.push({ requestId, body });
      requests.find(item => item.request_id === requestId).review_decision = body.decision;
      data = { ok: true, request_id: requestId, decision: body.decision, reviewed_at: '2026-10-16T13:00:00Z' };
    }
    await route.fulfill({ json: data });
  });
  await page.goto('/leads/7');
  await page.getByRole('button', { name: 'Skip onboarding' }).click();
  await expect(page.getByText('Sending paused for review')).toHaveCount(2);
  const confirmed = page.getByRole('listitem').filter({ hasText: 'Recipient campaign' });
  await expect(confirmed.getByText('Confirmed by recipient')).toBeVisible();
  await expect(confirmed.getByRole('button', { name: 'Reject request' })).toHaveCount(0);
  await expect(confirmed.getByRole('button', { name: 'Accept unsubscribe' })).toHaveCount(0);
  const first = page.getByRole('listitem').filter({ hasText: '2 requests' });
  await first.getByRole('button', { name: 'Reject request' }).click();
  await expect(page.getByText('An older Beacon page may already have shown the recipient a success message.')).toBeVisible();
  await page.getByRole('button', { name: 'OK' }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]).toEqual({ requestId: 31, body: { decision: 'rejected' } });
  await expect(first.getByText('Rejected')).toBeVisible();
  const second = page.getByRole('listitem').filter({ hasText: 'Other' });
  await second.getByRole('button', { name: 'Accept unsubscribe' }).click();
  await page.getByRole('button', { name: 'OK' }).click();
  await expect.poll(() => writes.length).toBe(2);
  expect(writes[1]).toEqual({ requestId: 32, body: { decision: 'accepted' } });
  await expect(second.getByText('Accepted')).toBeVisible();
});
