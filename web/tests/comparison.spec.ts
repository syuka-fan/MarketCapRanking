import { expect, test } from '@playwright/test';
import { createMarketFixture, mockMarket } from './fixtures/market';

test.beforeEach(async ({ page }) => { await page.emulateMedia({ reducedMotion: 'reduce' }); });

for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
  for (const count of [10, 20, 30, 40, 50]) {
    test(`${count} comparisons render within a ${viewport.width}px viewport`, async ({ page }, testInfo) => {
      const errors: string[] = [];
      page.on('pageerror', error => errors.push(error.message));
      const fixture = createMarketFixture(60);
      await mockMarket(page, fixture);
      await page.setViewportSize(viewport);
      await page.goto('/');
      await page.locator('#top').selectOption(String(count));
      await expect(page.locator('#chart-count')).toContainText(`${count}개 종목 ·`);
      await expect(page.locator('#selected .chip')).toHaveCount(count);
      await expect(page.locator('#chart-empty')).toBeHidden();
      await expect(page.locator('#chart canvas')).toBeVisible();
      const geometry = await page.evaluate(() => {
        const chart = document.querySelector('#chart')!.getBoundingClientRect();
        const chips = document.querySelector('#selected')!;
        const styles = [...chips.querySelectorAll<HTMLElement>('.chip')].map(chip => chip.getAttribute('style'));
        // Check actual canvas pixels as well as selection UI, so a blank chart fails.
        const canvas = document.querySelector<HTMLCanvasElement>('#chart canvas')!;
        const pixels = canvas.getContext('2d')!.getImageData(0, 0, canvas.width, canvas.height).data;
        let colored = 0;
        for (let i = 0; i < pixels.length; i += 4) {
          if (pixels[i + 3] > 150 && Math.max(pixels[i], pixels[i + 1], pixels[i + 2]) > 170
            && Math.max(pixels[i], pixels[i + 1], pixels[i + 2]) - Math.min(pixels[i], pixels[i + 1], pixels[i + 2]) > 35) colored++;
        }
        return { overflow: document.documentElement.scrollWidth > innerWidth, chartHeight: chart.height,
          chipHeight: chips.clientHeight, uniqueStyles: new Set(styles).size, colored };
      });
      expect(geometry.overflow).toBe(false);
      expect(geometry.chipHeight).toBeLessThanOrEqual(116);
      expect(geometry.uniqueStyles).toBe(count);
      expect(geometry.colored).toBeGreaterThan(count * 20);
      if (count > 20) expect(geometry.chartHeight).toBeGreaterThanOrEqual(count * 12);
      await page.locator('.chart-panel').screenshot({ path: testInfo.outputPath('chart.png'), animations: 'disabled' });

      // The 50-row tooltip must fit and permit access to its last row on desktop and mobile.
      if (count === 50) {
        await page.locator('#chart').scrollIntoViewIfNeeded();
        const box = (await page.locator('#chart').boundingBox())!;
        await page.mouse.move(box.x + box.width * 0.75, box.y + box.height * 0.3);
        const tooltip = page.locator('.tooltip-list');
        await expect(tooltip).toBeVisible();
        await expect(tooltip.locator('.chart-tooltip')).toHaveCount(50);
        const bounds = await tooltip.evaluate(element => {
          const rect = element.getBoundingClientRect();
          return { left: rect.left, right: rect.right, height: rect.height, scrollHeight: element.scrollHeight, viewport: innerWidth };
        });
        expect(bounds.left).toBeGreaterThanOrEqual(0);
        expect(bounds.right).toBeLessThanOrEqual(bounds.viewport);
        expect(bounds.height).toBeLessThanOrEqual(280);
        expect(bounds.scrollHeight).toBeGreaterThan(bounds.height);
        await page.locator('.chart-panel').screenshot({ path: testInfo.outputPath('tooltip.png') });
        await tooltip.hover();
        await page.mouse.wheel(0, 4000);
        await expect.poll(() => tooltip.evaluate(element => element.scrollTop)).toBeGreaterThan(0);
        await expect(tooltip.locator('.chart-tooltip').last()).toBeInViewport();
        await page.mouse.move(0, 0);
        await page.locator('#selected .chip').last().focus();
        await expect(page.locator('#selected .chip').last()).toBeInViewport();
        await page.locator('.chart-panel').screenshot({ path: testInfo.outputPath('highlight.png') });
      }
      expect(errors).toEqual([]);
    });
  }
}

test('50-item limit allows replacing a ticker and reducing the preset', async ({ page }) => {
  await mockMarket(page, createMarketFixture(60));
  await page.goto('/');
  await page.locator('#top').selectOption('50');
  await expect(page.locator('#chart-count')).toContainText('50개 종목');
  await page.locator('#more').click();
  const extra = page.locator('#rows .compare').nth(50);
  await extra.click();
  await expect(page.locator('#notice')).toContainText('최대 50개');
  await expect(extra).toHaveAttribute('aria-pressed', 'false');
  await page.locator('#selected .chip').first().click();
  await expect(page.locator('#chart-count')).toContainText('49개 종목');
  await extra.click();
  await expect(extra).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('#chart-count')).toContainText('50개 종목');
  await page.locator('#top').selectOption('10');
  await expect(page.locator('#chart-count')).toContainText('10개 종목');
  await expect(page.locator('#selected .chip')).toHaveCount(10);
  expect((await page.locator('#chart').boundingBox())!.height).toBeLessThan(400);
});

test('50-item preset uses available tickers without fabricating extra data', async ({ page }) => {
  await mockMarket(page, createMarketFixture(12));
  await page.goto('/');
  await page.locator('#top').selectOption('50');
  await expect(page.locator('#chart-count')).toContainText('12개 종목');
  await expect(page.locator('#selected .chip')).toHaveCount(12);
});

test('single-day history draws points for 50 tickers', async ({ page }, testInfo) => {
  await mockMarket(page, createMarketFixture(60, 1));
  await page.goto('/');
  await page.locator('#top').selectOption('50');
  await expect(page.locator('#chart-count')).toHaveText('50개 종목 · 1개 거래일');
  await expect(page.locator('#chart-empty')).toBeHidden();
  await page.locator('.chart-panel').screenshot({ path: testInfo.outputPath('single-day.png') });
});

test('50 comparisons follow period and date changes with incomplete histories', async ({ page }) => {
  const fixture = createMarketFixture(60);
  await mockMarket(page, fixture);
  await page.goto('/');
  await page.locator('#top').selectOption('50');
  await page.locator('#period').selectOption('all');
  await expect(page.locator('#chart-count')).toHaveText('50개 종목 · 130개 거래일');
  const gapDay = fixture.index.dates[65];
  await page.locator('#date').selectOption(gapDay);
  await expect(page.locator('#chart-count')).toHaveText('50개 종목 · 66개 거래일');
  await page.locator('#period').selectOption('1');
  await expect(page.locator('#chart-count')).toHaveText(/50개 종목 · 2[0-3]개 거래일/);
});
