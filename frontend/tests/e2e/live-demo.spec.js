import { test, expect } from '@playwright/test';
test('live demo streams a response', async ({ page }) => { await page.goto('/live-demo'); await page.locator('textarea').fill('What does invoice 4471 cover?'); await page.getByRole('button', { name: /send/i }).click(); await expect(page.getByText(/invoice|consulting/i).last()).toBeVisible({ timeout: 25000 }); });
