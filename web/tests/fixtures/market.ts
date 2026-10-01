import type { Page } from '@playwright/test';
import type { Index, Instrument, Point, Row } from '../../src/types';

// Synthetic responses exist only in the test runner; never write them to public/data.
export function createMarketFixture(count = 26, dayCount = 130) {
  const dates: string[] = [];
  const cursor = new Date('2026-09-30T12:00:00Z');
  while (dates.length < dayCount) {
    if (cursor.getUTCDay() !== 0 && cursor.getUTCDay() !== 6) dates.unshift(cursor.toISOString().slice(0, 10));
    cursor.setUTCDate(cursor.getUTCDate() - 1);
  }
  const instruments: Instrument[] = Array.from({ length: count }, (_, i) => ({
    id: `TEST${i.toString().padStart(3, '0')}`,
    name: i < 2 ? 'Northstar (가상)' : i % 7 === 0 ? `아주 긴 이름의 글로벌 테크놀로지 인덱스 펀드 ${i} (가상)` : `테스트 종목 ${i} (가상)`,
    tickers: [i === 0 ? 'D00A' : i === 1 ? 'D00B' : `D${i.toString().padStart(2, '0')}A`],
    history_file: `TEST${i.toString().padStart(3, '0')}.json`,
  }));
  const histories: Record<string, Record<string, Point>> = Object.fromEntries(instruments.map(c => [c.history_file, {}]));
  const days: Record<string, { rows: Row[] }> = {};
  for (const [t, day] of dates.entries()) {
    // Crossing ranks, long names, a new listing and a missing observation exercise dense charts.
    const ranked = instruments.map((instrument, i) => ({
      instrument, i, score: 180 - i * 1.5 + 8 * Math.sin(t / 8 + i * 0.9) + 3 * Math.cos(t / 17 + i),
    })).filter(({ i }) => !(i === 7 && t === Math.floor(dayCount / 2)) && !(i === count - 1 && t < dayCount / 3))
      .sort((a, b) => b.score - a.score);
    const rows: Row[] = ranked.map(({ instrument, score }, rank) => {
      const close = Math.round(score * 100) / 100;
      const point: Point = { rank: rank + 1, market_cap_usd: close * 1_000_000_000, prices: [{ ticker: instrument.tickers[0], close }] };
      const previous = histories[instrument.history_file][dates[t - 1]];
      histories[instrument.history_file][day] = point;
      return { ...point, instrument_id: instrument.id, company_name: instrument.name, ticker: instrument.tickers[0],
        security_type: 'CS', shares_outstanding: '1000000000', shares_source: 'test fixture',
        rank_change: previous ? previous.rank - point.rank : null, change_state: previous ? 'known' : 'baseline' };
    });
    days[day] = { rows };
  }
  const index: Index = { schema_version: 2, dates, closed_dates: dates, axis_dates: dates, instruments, is_demo: true, source: 'test fixture',
    scope: '브라우저 테스트 전용 가상 종목', method: '합성 순위 이력',
    status: { state: 'success', last_success_at: '2026-09-30T21:00:00Z', latest_trade_date: dates.at(-1)! } };
  return { index, days, histories };
}

export async function mockMarket(page: Page, fixture = createMarketFixture()) {
  await page.route('**/data/**', route => {
    const path = new URL(route.request().url()).pathname.split('/data/')[1];
    const value = path === 'index.json' ? fixture.index
      : path.startsWith('days/') ? fixture.days[path.slice(5, -5)]
      : path.startsWith('instruments/') ? fixture.histories[path.slice(12)] : undefined;
    return value ? route.fulfill({ json: value }) : route.fulfill({ status: 404 });
  });
}
