import { test, expect } from '@playwright/test';

test('shared dropdowns work on notifications, schedule and unibox', async ({ page }) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    const data = {
      '/api/auth/setup-status': { setup_complete: true },
      '/api/auth/refresh': { access_token: 'test' },
      '/api/auth/me': { id: 1, email: 'owner@example.com', role: 'admin', name: 'Owner' },
      '/api/status': { app_mode: 'production', test_mode: true },
      '/api/notifications': { items: [], total: 0, unread: 0 },
      '/api/notifications/config': { enabled: false, notification_email: '', events: [], rate_limit_per_hour: 10 },
      '/api/settings/webhooks/events': { events: [] },
      '/api/schedule/sent': [],
      '/api/schedule/scheduled': [],
      '/api/schedule/stats': { total_sent: 0, total_scheduled: 0, total_campaigns: 0 },
      '/api/settings/scheduling-strategy': { scheduling_strategy: 'priority' },
      '/api/unibox': { items: [], total: 0 },
    }[path] ?? {};
    await route.fulfill({ json: data });
  });

  await page.goto('/notifications');
  await page.getByRole('button', { name: 'Skip onboarding' }).click();
  await page.getByRole('combobox', { name: 'Category' }).selectOption('email');
  await expect(page.getByRole('combobox', { name: 'Category' })).toHaveValue('email');
  await page.getByRole('button', { name: 'Clear filters' }).click();
  await expect(page.getByRole('combobox', { name: 'Category' })).toHaveValue('');

  await page.goto('/schedule');
  await page.getByRole('combobox', { name: 'Send state' }).selectOption('scheduled');
  await expect(page.getByRole('combobox', { name: 'Send state' })).toHaveValue('scheduled');
  await page.getByRole('button', { name: 'Clear filters' }).click();
  await expect(page.getByRole('combobox', { name: 'Send state' })).toHaveValue('');

  await page.goto('/unibox');
  await expect(page.getByRole('combobox', { name: 'Lead status' })).toHaveValue('');
  await page.getByRole('combobox', { name: 'Lead status' }).selectOption('active');
  await expect(page.getByRole('combobox', { name: 'Lead status' })).toHaveValue('active');
  await page.getByRole('button', { name: 'Clear filter' }).click();
  await expect(page.getByRole('combobox', { name: 'Lead status' })).toHaveValue('');
  expect(pageErrors).toEqual([]);
});
