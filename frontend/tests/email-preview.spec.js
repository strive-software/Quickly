import { test, expect } from '@playwright/test';

async function mockCampaign(page, sentBody = 'The original sent message\nSecond line', sentHtml = false) {
  const metadata = { lead_email: 'alex@example.com', inbox_email: 'sender@example.com', campaign_name: 'Preview test', sequence_index: 0 };
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    const data = {
      '/api/auth/setup-status': { setup_complete: true },
      '/api/auth/refresh': { access_token: 'local-test-only' },
      '/api/auth/me': { id: 1, email: 'test@example.com', role: 'admin', name: 'Test' },
      '/api/status': { app_mode: 'production', test_mode: true },
      '/api/inboxes': [],
      '/api/campaigns/1': { id: 1, name: 'Preview test', paused: true, inbox_ids: [], timezone: 'UTC' },
      '/api/campaigns/1/sequences': [],
      '/api/campaigns/1/leads': [],
      '/api/campaigns/1/queue': [{ ...metadata, slot_id: 4, scheduled_date: '2026-10-20T09:00:00', position_in_day: 1 }],
      '/api/campaigns/1/sent': [{ ...metadata, log_id: 5, sent_at: '2026-10-13T09:00:00', subject: 'Original subject' }],
      '/api/campaigns/1/analytics/steps': [],
      '/api/analytics/daily': [],
      '/api/schedule/scheduled/4': { ...metadata, subject: 'For Alex', sequence_body: '<p>Personalized <strong>Alex</strong></p><img src="https://tracker.example/pixel"><style>body{background:url(https://tracker.example/css)}</style><script>parent.previewScriptExecuted=true</script>', sequence_is_html: true },
      '/api/schedule/sent/5': { ...metadata, subject: 'Original subject', sequence_body: sentBody, sequence_is_html: sentHtml, body_available: sentBody !== null },
    }[path] ?? {};
    await route.fulfill({ json: data });
  });
}

test('queue preview shows personalized HTML without scripts or tracking requests', async ({ page }) => {
  await mockCampaign(page);
  const tracking = [];
  page.on('request', request => { if (request.url().includes('tracker.example')) tracking.push(request.url()); });
  await page.goto('/campaigns/1#queue');
  await page.getByRole('button', { name: 'Skip onboarding' }).click();
  await page.getByRole('button', { name: 'Preview email', exact: true }).click();
  const modal = page.getByRole('dialog', { name: 'Email Preview' });
  await expect(modal).toContainText('For Alex');
  await expect(modal).toContainText('sender@example.com');
  await expect(modal.frameLocator('iframe').locator('strong')).toHaveText('Alex');
  await expect.poll(() => modal.frameLocator('iframe').locator('body').evaluate(node => node.ownerDocument.readyState)).toBe('complete');
  expect(await page.evaluate(() => window.previewScriptExecuted)).toBeUndefined();
  expect(tracking).toEqual([]);
  await modal.getByRole('button', { name: 'Close', exact: true }).click();
  await expect(modal).toHaveCount(0);
});

for (const format of ['plain', 'html', 'historical']) {
  test(`analytics views ${format} sent content without tracking requests`, async ({ page }) => {
    const sentBody = format === 'historical' ? null : format === 'html'
      ? '<p>The original <strong>sent message</strong></p><img src="https://tracker.example/sent-pixel" onerror="parent.previewScriptExecuted=true"><style>body{background:url(https://tracker.example/sent-css)}</style>'
      : 'The original sent message\nSecond line';
    await mockCampaign(page, sentBody, format === 'html');
    const tracking = [];
    page.on('request', request => { if (request.url().includes('tracker.example')) tracking.push(request.url()); });
    await page.goto('/campaigns/1#analytics');
    await page.getByRole('button', { name: 'Skip onboarding' }).click();
    await page.getByRole('button', { name: 'Sent Emails', exact: true }).click();
    await page.getByRole('button', { name: 'View email', exact: true }).click();
    const modal = page.getByRole('dialog', { name: 'Email Preview' });
    await expect(modal).toContainText('Original subject');
    if (format === 'historical') await expect(modal).toContainText('Original body unavailable');
    else if (format === 'html') {
      await expect(modal.frameLocator('iframe').locator('strong')).toHaveText('sent message');
      await expect.poll(() => modal.frameLocator('iframe').locator('body').evaluate(node => node.ownerDocument.readyState)).toBe('complete');
    }
    else await expect(modal.locator('pre')).toHaveText('The original sent message\nSecond line');
    expect(await page.evaluate(() => window.previewScriptExecuted)).toBeUndefined();
    expect(tracking).toEqual([]);
  });
}
