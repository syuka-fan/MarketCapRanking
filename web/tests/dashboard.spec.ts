import { expect, test } from '@playwright/test';
import { createMarketFixture, mockMarket } from './fixtures/market';

test.beforeEach(async ({ page }) => { await mockMarket(page); });

test('fictional preview supports search, multiple tickers, dates and comparison', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('/');
  await expect(page.getByRole('status')).toContainText('가상 종목');
  await expect(page.locator('#stat-companies')).toHaveText('26');
  await expect(page.locator('#chart canvas')).toBeVisible();
  await page.getByRole('searchbox').fill('D00');
  await expect(page.locator('#rows tr')).toHaveCount(2);
  await expect(page.locator('#rows .tickers')).toHaveText(['D00A · 보통주', 'D00B · 보통주']);
  await expect(page.locator('#rows .prices div')).toHaveCount(2);
  const comparison = page.getByRole('button', { name: 'Northstar (가상) (D00A) 비교', exact: true });
  const before = await comparison.getAttribute('aria-pressed');
  await comparison.click();
  await expect(comparison).toHaveAttribute('aria-pressed', before === 'true' ? 'false' : 'true');
  await page.locator('#date').selectOption('2026-09-29');
  await expect(page.locator('#asof-date')).toHaveText('2026.09.29');
  await page.locator('#period').selectOption('all');
  await expect(page.locator('#chart-count')).toContainText('거래일');
  expect(errors).toEqual([]);
});

test('empty data shows an honest empty state', async ({ page }) => {
  await page.route('**/data/index.json', route => route.fulfill({ status: 200, json: {
    schema_version: 2, dates: [], axis_dates: [], instruments: [], status: { state: 'empty' }, is_demo: false,
  } }));
  await page.goto('/');
  await expect(page.locator('#rows')).toContainText('첫 거래일 데이터');
  await expect(page.getByRole('searchbox')).toBeDisabled();
  await expect(page.locator('#stat-days')).toHaveText('0');
});

test('failed updates retain last data and show failure', async ({ page }) => {
  await page.route('**/data/index.json', async route => {
    const data = createMarketFixture().index;
    data.status.state = 'error';
    await route.fulfill({ json: data });
  });
  await page.goto('/');
  await expect(page.getByRole('status')).toContainText('최근 갱신에 실패');
  await expect(page.locator('#stat-companies')).toHaveText('26');
});

test('mobile viewport keeps the page within its width', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await expect(page.locator('#stat-companies')).toHaveText('26');
  const overflows = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
  expect(overflows).toBe(false);
  await page.screenshot({ path: 'test-results/dashboard-mobile.png', fullPage: true });
});

test('provisional quotes are labeled and excluded from the closing chart', async ({ page }) => {
  await page.route('**/data/index.json', async route => {
    const data = createMarketFixture().index;
    data.is_demo = false;
    data.provisional_date = data.dates.at(-1);
    data.provisional_at = '2026-09-30T15:00:00Z';
    data.closed_dates = [];
    data.axis_dates = [];
    await route.fulfill({ json: data });
  });
  await page.goto('/');
  await expect(page.getByRole('status')).toContainText('장중·잠정 데이터');
  await expect(page.locator('#price-heading')).toHaveText('장중 가격 (잠정)');
  await expect(page.locator('#stat-days')).toHaveText('0');
  await expect(page.locator('#chart-empty')).toContainText('첫 장 마감 후');
  await expect(page.locator('#download')).toContainText('장중·잠정');
  await page.locator('#date').selectOption('2026-09-29');
  await expect(page.locator('#price-heading')).toHaveText('본장 종가');
  await expect(page.locator('#notice')).not.toContainText('장중·잠정 데이터');
});

test('historical prices are downloadable without inventing historical ranks', async ({ page }) => {
  await page.route('**/data/index.json', async route => {
    const data = createMarketFixture().index;
    data.closed_dates = [];
    data.axis_dates = [];
    data.provisional_date = data.dates.at(-1);
    data.price_dates = ['2026-09-29', '2026-09-30'];
    data.close_history_file = 'close-history.csv';
    await route.fulfill({ json: data });
  });
  await page.goto('/');
  await expect(page.locator('#close-history')).toContainText('종가 2거래일');
  await expect(page.locator('#close-history-download')).toHaveAttribute('href', './data/close-history.csv');
  await expect(page.locator('#stat-days')).toHaveText('0');
  await expect(page.locator('#chart-empty')).toContainText('종가 2거래일은 CSV로 제공');
});
