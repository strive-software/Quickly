import { test, expect } from '@playwright/test';

for (const html of [false, true]) {
  test(`reopens and saves personalized ${html ? 'HTML' : 'plain text'} content`, async ({ page }) => {
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const saved = { subject: 'For Alex', body: html ? '<p>Hello <strong>Alex</strong></p>' : 'Hello Alex\nA personal note', is_html: html };
    const writes = [];
    await page.route('**/api/**', async route => {
      const path = new URL(route.request().url()).pathname;
      let data = {};
      if (path === '/api/auth/setup-status') data = { setup_complete: true };
      if (path === '/api/auth/refresh') data = { access_token: 'local-test-only' };
      if (path === '/api/auth/me') data = { id: 1, email: 'test@example.com', role: 'admin', name: 'Test' };
      if (path === '/api/status') data = { app_mode: 'production', test_mode: true };
      if (path === '/api/inboxes') data = [];
      if (path === '/api/campaigns/1') data = { id: 1, name: 'Paused test', paused: true, inbox_ids: [], sending_days: [1], timezone: 'UTC', custom_sequence_mode: 'wait_for_all' };
      if (path === '/api/campaigns/1/sequences') data = [{ id: 11, campaign_id: 1, position: 0, sequence_type: 'personalized', subject: '', body: '', is_html: !html, variants: [] }];
      if (path === '/api/campaigns/1/leads') data = [{ lead_id: 2, campaign_lead_id: 3, email: 'alex@example.com', status: 'active', name: 'Alex', personalized: [{ sequence_id: 11, sequence_position: 0, written: true, already_sent: false, ...saved }] }];
      if (path === '/api/campaigns/1/queue' || path === '/api/campaigns/1/sent') data = [];
      if (path === '/api/campaigns/1/leads/2/custom-email/11') {
        const update = route.request().postDataJSON();
        writes.push(update);
        Object.assign(saved, update);
        data = { ok: true };
      }
      await route.fulfill({ json: data });
    });
    await page.goto('/campaigns/1#sequences');
    await page.getByRole('button', { name: 'Skip onboarding' }).click();
    await page.getByRole('button', { name: /^Written/ }).click();
    await page.getByRole('row').filter({ hasText: 'alex@example.com' }).getByRole('button', { name: 'Edit', exact: true }).click();
    const modal = page.locator('.fixed').filter({ has: page.getByText('Compose your custom email for this lead.', { exact: true }) });
    await expect(modal.locator('input[type="text"], input:not([type])').first()).toHaveValue('For Alex');
    const checkbox = modal.getByRole('checkbox', { name: 'Send as HTML' });
    if (html) {
      await expect(checkbox).toBeChecked();
      await expect(modal.locator('.ql-editor')).toContainText('Hello Alex');
      await expect(modal.locator('.ql-editor strong')).toHaveText('Alex');
    } else {
      await expect(checkbox).not.toBeChecked();
      await expect(modal.locator('textarea')).toHaveValue(saved.body);
    }
    await modal.getByRole('button', { name: 'Save', exact: true }).click();
    await expect.poll(() => writes.length).toBe(1);
    expect(writes[0].subject).toBe('For Alex');
    expect(writes[0].is_html).toBe(html);
    expect(writes[0].body).toContain(html ? '<strong>Alex</strong>' : 'A personal note');
    expect(errors).toEqual([]);
  });
}
