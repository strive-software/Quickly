import { test, expect } from '@playwright/test';

test('unmapped custom checker results do not mark the connection tested', async ({ page }) => {
  const testRequests = [];
  await page.route('**/api/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    let data = {
      '/api/auth/setup-status': { setup_complete: true },
      '/api/auth/refresh': { access_token: 'test' },
      '/api/auth/me': { id: 1, email: 'owner@example.com', role: 'admin', name: 'Owner' },
      '/api/status': { app_mode: 'production', test_mode: true },
      '/api/settings/email-verification': {
        enabled: false, provider: 'custom', providers: ['custom'],
        custom_url: 'https://checker.example/verify?email={email}',
        custom_field_path: 'status', custom_valid_values: ['valid'],
        custom_invalid_values: ['invalid'], custom_method: 'GET', connection_tested: true,
      },
      '/api/settings/email-verification/test-custom': {
        connection_tested: false,
        results: [{ email: 'alex@example.com', status: 'unknown', failed: true, raw_field_value: 'maybe' }],
      },
      '/api/settings/webhooks': [], '/api/settings/webhooks/events': { events: [] },
      '/api/settings/ai/providers': { providers: [] }, '/api/settings/known-ips': { known_ips: [] },
      '/api/auth/api-keys': [],
    }[path] ?? {};
    if (path === '/api/settings/email-verification/test-custom' && request.method() === 'POST') {
      const body = request.postDataJSON();
      testRequests.push(body);
      if (body.persist_configuration === false) data = { connection_tested: false, results: [{ email: body.test_emails[0], raw_response: { status: 'maybe' } }] };
    }
    await route.fulfill({ json: data });
  });
  await page.goto('/settings#features');
  await page.getByRole('button', { name: 'Skip onboarding' }).click();
  await page.getByRole('heading', { name: 'Email Verification', exact: true }).click();
  await page.getByRole('button', { name: 'Preview response' }).click();
  await expect.poll(() => testRequests.length).toBe(1);
  expect(testRequests[0].persist_configuration).toBe(false);
  await page.getByRole('button', { name: 'Run test' }).click();
  await expect.poll(() => testRequests.length).toBe(2);
  expect(testRequests[1]).not.toHaveProperty('persist_configuration');
  await expect(page.getByRole('alert').filter({ hasText: 'No checker response matched' })).toBeVisible();
  await expect(page.getByText('Test connection before enabling')).toBeVisible();
  await expect(page.getByText('Needs mapping')).toBeVisible();
});
