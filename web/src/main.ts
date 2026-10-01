import * as echarts from 'echarts/core';
import { LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, DataZoomComponent, AriaComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import type { Instrument, Index, Point, Row } from './types';
import './style.css';

echarts.use([LineChart, GridComponent, TooltipComponent, DataZoomComponent, AriaComponent, CanvasRenderer]);

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const escape = (value: unknown) => String(value).replace(/[&<>"']/g, c => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[c]!));
const number = new Intl.NumberFormat('ko-KR');
const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 });
const cap = (value: number) => value >= 1e12 ? `$${(value / 1e12).toFixed(2)}조` : `$${(value / 1e8).toFixed(1)}억`;
const palette = ['#82ecc3', '#8db9ff', '#ddb0ff', '#f6c67e', '#ed9fab', '#83dbea', '#bed989', '#adadff', '#f4a87a', '#76cab5'];
const color = (id: string) => palette[Array.from(id).reduce((n, c) => (n * 31 + c.charCodeAt(0)) >>> 0, 0) % palette.length];
const instrumentLabel = (item: Instrument) => `${item.name} (${item.tickers.at(-1)})`;

$('app').innerHTML = `
  <header class="header shell">
    <a class="brand" href="./" aria-label="MarketCap 홈"><span class="brand-icon" aria-hidden="true"><i></i><i></i><i></i></span>MarketCap<span class="brand-dot">.</span></a>
    <span class="header-tag">US EQUITY OBSERVATORY</span>
    <div class="schedule"><span class="pulse"></span> 화–토 09:00 KST 갱신 예약</div>
  </header>
  <main class="shell">
    <div id="notice" class="notice" role="status" hidden></div>
    <section class="hero">
      <div><div class="eyebrow">매일 기록하는 시장의 순서</div><h1>종목의 가치,<br class="mobile-break"> 순위의 변화.</h1><p class="hero-copy">미국 본장 종가로 살펴보는 종목 시가총액과 일별 순위 기록</p></div>
      <div class="asof"><span class="label">미국 기준 거래일</span><strong id="asof-date">—</strong><span id="updated-at">데이터를 불러오는 중입니다</span></div>
    </section>
    <section class="stats" aria-label="시장 요약">
      <div><span class="label">기록된 종목</span><strong id="stat-companies">—</strong><small>티커별 독립 순위</small></div>
      <div><span class="label">대상 종목 시가총액 합계</span><strong id="stat-cap">—</strong><small id="price-basis">USD · 본장 종가 기준</small></div>
      <div><span class="label">누적 거래일</span><strong id="stat-days">—</strong><small id="history-range">일별 기록을 준비하고 있습니다</small></div>
    </section>
    <section class="panel chart-panel" aria-labelledby="chart-heading">
      <div class="section-top"><div><div class="eyebrow">RANK HISTORY</div><h2 id="chart-heading">순위의 흐름</h2><p class="muted">위로 갈수록 높은 순위입니다. 종목을 선택해 흐름을 비교하세요.</p></div>
        <div class="controls"><label>비교 종목<select id="top" disabled><option value="10">상위 10개</option><option value="20">상위 20개</option></select></label><label>조회 기간<select id="period" disabled><option value="1">1개월</option><option value="3" selected>3개월</option><option value="12">1년</option><option value="all">전체</option></select></label></div></div>
      <div id="selected" class="chips" aria-label="비교 중인 종목"></div>
      <div id="chart" role="img" aria-label="종목별 거래일 순위 변화 그래프"></div>
      <div id="chart-empty" class="chart-empty">첫 거래일 데이터가 준비되면 순위 변화가 표시됩니다.</div>
      <div class="chart-foot"><span id="chart-count">종목별 이력을 누적합니다</span><span>순위 · 낮은 숫자가 상위</span></div>
    </section>
    <section class="panel table-panel" aria-labelledby="table-heading">
      <div class="section-top"><div><div class="eyebrow">DAILY RANKING</div><h2 id="table-heading">시가총액 순위</h2></div><div class="table-tools"><label class="search-label"><span class="sr-only">종목명 또는 티커 검색</span><input id="search" type="search" placeholder="종목명 또는 티커 검색" disabled /></label><label><span class="sr-only">거래일 선택</span><select id="date" disabled><option>거래일 선택</option></select></label><a id="download" class="download" hidden>최신 종가 CSV ↗</a></div></div>
      <div class="table-scroll"><table><thead><tr><th scope="col">순위</th><th scope="col">종목 / 티커</th><th id="price-heading" scope="col" class="numeric">본장 종가</th><th scope="col" class="numeric">시가총액</th><th scope="col" class="numeric">순위 변동</th><th scope="col"><span class="sr-only">그래프 비교</span></th></tr></thead><tbody id="rows"><tr><td colspan="6" class="empty-cell">데이터를 불러오는 중입니다.</td></tr></tbody></table></div>
      <div class="table-foot"><span id="table-count">—</span><button id="more" hidden>더 보기</button><span>변동은 직전 미국 거래일 대비</span></div>
    </section>
    <details class="method"><summary>데이터와 순위 산정 기준</summary><p id="method-text">종목별 시가총액을 비교하며, 같은 회사의 주식 클래스도 티커별로 따로 기록합니다.</p><p>각 티커의 가격 × 해당 티커의 발행 주식수(ADR·ETF는 예탁증권·상장좌수)로 계산합니다. 회사 전체 환산 시총이나 펀드 전체 순자산을 대신 사용하지 않습니다. 같은 회사라도 티커를 합치지 않습니다. 공개 데이터의 확인 가능한 종목 범위에 따른 순위이며, 순위는 반올림 표시 전 값으로 계산합니다.</p><p>휴장일에는 마지막 거래일을 유지합니다. 데이터가 없는 거래일은 선을 연결하지 않습니다. 수집 전 과거의 시가총액은 임의로 복원하지 않습니다. 예약 실행이 지연될 수 있으며, 갱신 시각은 실제 수집 완료 시각입니다.</p></details>
  </main>
  <footer class="shell footer"><span>MarketCap. <span class="muted">매일의 시장을 기록합니다.</span></span><span id="source">REGULAR SESSION CLOSE · USD</span></footer>
`;

let index: Index;
let rows: Row[] = [];
let selected = new Set<string>();
let pageSize = 50;
let displayedDate = '';
let baseNotice = '';
let dayRequest = 0;
let chartRequest = 0;
const history = new Map<string, Record<string, Point>>();
const chart = echarts.init($('chart'), undefined, { renderer: 'canvas' });
new ResizeObserver(() => chart.resize()).observe($('chart'));

async function json<T>(path: string): Promise<T> {
  const response = await fetch(`./data/${path}`, { cache: 'no-cache' });
  if (!response.ok) throw new Error(`Data request failed (${response.status})`);
  return await response.json() as T;
}

function notice(message: string) {
  const fullMessage = [baseNotice, message].filter(Boolean).join(' ');
  $('notice').textContent = fullMessage;
  $('notice').hidden = !fullMessage;
}

function change(row: Row): string {
  if (row.change_state === 'new') return '<span class="delta new">NEW</span>';
  if (row.rank_change === null) return '<span class="delta flat" title="직전 거래일 비교 데이터 없음">—</span>';
  if (row.rank_change === 0) return '<span class="delta flat">–</span>';
  return `<span class="delta ${row.rank_change > 0 ? 'up' : 'down'}">${row.rank_change > 0 ? '↑' : '↓'} ${Math.abs(row.rank_change)}</span>`;
}

function renderTable() {
  const query = $<HTMLInputElement>('search').value.trim().toLocaleLowerCase();
  const filtered = rows.filter(r => `${r.company_name} ${r.prices.map(p => p.ticker).join(' ')}`.toLocaleLowerCase().includes(query));
  $('rows').innerHTML = filtered.slice(0, pageSize).map(r => `
    <tr class="${selected.has(r.instrument_id) ? 'is-selected' : ''}">
      <td class="rank">${r.rank.toString().padStart(2, '0')}</td>
      <td><div class="company-cell"><span class="avatar" style="--company-color:${color(r.instrument_id)}">${escape(r.company_name.slice(0, 1))}</span><span><strong>${escape(r.company_name)}</strong><span class="tickers">${escape(r.ticker)} · ${r.security_type === 'CS' ? '보통주' : escape(r.security_type)}</span></span></div></td>
      <td class="numeric prices">${r.prices.map(p => `<div>${r.prices.length > 1 ? `<small>${escape(p.ticker)}</small> ` : ''}${usd.format(p.close)}${p.quote_date && p.quote_date !== displayedDate ? ` <small>(${escape(p.quote_date)} 최종 체결)</small>` : ''}</div>`).join('')}</td>
      <td class="numeric market-cap" title="${usd.format(r.market_cap_usd)} · 발행수 ${number.format(Number(r.shares_outstanding))} · ${escape(r.shares_source)}">${cap(r.market_cap_usd)}</td><td class="numeric">${change(r)}</td>
      <td><button class="compare ${selected.has(r.instrument_id) ? 'active' : ''}" data-company="${escape(r.instrument_id)}" aria-label="${escape(r.company_name)} (${escape(r.ticker)}) 비교" aria-pressed="${selected.has(r.instrument_id)}">${selected.has(r.instrument_id) ? '✓' : '+'}</button></td>
    </tr>`).join('') || '<tr><td colspan="6" class="empty-cell">검색 결과가 없습니다.</td></tr>';
  $('table-count').textContent = `${number.format(filtered.length)}개 종목 중 ${Math.min(pageSize, filtered.length)}개 표시`;
  $('more').hidden = pageSize >= filtered.length;
}

function renderChips() {
  $('selected').innerHTML = [...selected].map(id => {
    const company = index.instruments.find(c => c.id === id)!;
    return `<button class="chip" data-company="${escape(id)}" style="--company-color:${color(id)}" aria-label="${escape(instrumentLabel(company))} 비교 해제"><i></i>${escape(instrumentLabel(company))}<span>×</span></button>`;
  }).join('');
}

async function renderChart() {
  const request = ++chartRequest;
  renderChips();
  const companies = [...selected].map(id => index.instruments.find(c => c.id === id)!);
  try {
    await Promise.all(companies.map(async c => {
      if (!history.has(c.id)) history.set(c.id, await json<Record<string, Point>>(`instruments/${c.history_file}`));
    }));
    if (request !== chartRequest) return;
    const end = displayedDate;
    const period = $<HTMLSelectElement>('period').value;
    const start = new Date(`${end}T12:00:00Z`);
    if (period !== 'all') start.setUTCMonth(start.getUTCMonth() - Number(period));
    const lower = period === 'all' ? '' : start.toISOString().slice(0, 10);
    const dates = index.axis_dates.filter(d => d <= end && d >= lower);
    $('chart-empty').hidden = companies.length > 0 && dates.length > 0;
    $('chart-empty').textContent = dates.length ? '순위표의 + 버튼으로 비교할 종목을 선택하세요.' : '장중·잠정 순위는 이력에서 제외됩니다. 첫 장 마감 후 종가 기록을 시작합니다.';
    $('chart-count').textContent = `${companies.length}개 종목 · ${dates.length}개 거래일`;
    chart.setOption({
      animationDuration: 250, backgroundColor: 'transparent',
      aria: { enabled: true, label: { description: '미국 거래일별 종목 시가총액 순위. 1위가 가장 위에 표시됩니다.' } },
      grid: { top: 22, left: 45, right: 35, bottom: 58 },
      tooltip: { trigger: 'axis', backgroundColor: '#182231', borderColor: '#344153', textStyle: { color: '#e7edf5' },
        confine: true, formatter: (params: unknown) => {
          const entries = params as { axisValue: string; seriesId: string; color: string }[];
          if (!entries.length) return '';
          const day = entries[0].axisValue;
          return `<strong>${escape(day)} · 미국 거래일</strong>` + entries.map(entry => {
            const point = history.get(entry.seriesId)?.[day];
            const company = index.instruments.find(c => c.id === entry.seriesId);
            return point && company ? `<div class="chart-tooltip"><span style="color:${entry.color}">●</span> ${escape(company.name)} <b>${point.rank}위</b><br><small>${cap(point.market_cap_usd)} · ${point.prices.map(p => `${escape(p.ticker)} ${usd.format(p.close)}`).join(' / ')}</small></div>` : '';
          }).join('');
        } },
      xAxis: { type: 'category', data: dates, boundaryGap: false, axisLine: { lineStyle: { color: '#2b3543' } },
        axisTick: { show: false }, axisLabel: { color: '#8998aa', formatter: (d: string) => d.slice(5).replace('-', '.') } },
      yAxis: { type: 'value', inverse: true, min: 1, minInterval: 1,
        axisLabel: { color: '#8998aa', formatter: '{value}위' }, splitLine: { lineStyle: { color: '#202c3b', type: 'dashed' } } },
      dataZoom: [{ type: 'inside', filterMode: 'none' }, { type: 'slider', height: 14, bottom: 8, borderColor: 'transparent',
        backgroundColor: '#111c29', fillerColor: '#82ecc319', handleStyle: { color: '#6b9c8d' }, textStyle: { color: '#8998aa' } }],
      series: companies.map(c => ({ id: c.id, name: instrumentLabel(c), type: 'line', smooth: false, connectNulls: false,
        showSymbol: dates.length === 1, symbolSize: 5, lineStyle: { width: 2.2 }, itemStyle: { color: color(c.id) },
        emphasis: { focus: 'series', lineStyle: { width: 4 } },
        data: dates.map(d => history.get(c.id)?.[d]?.rank ?? null) })),
    }, true);
  } catch {
    if (request === chartRequest) notice('일부 종목의 순위 이력을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.');
  }
}

async function loadDay(resetSelection = false) {
  const request = ++dayRequest;
  try {
    const day = $<HTMLSelectElement>('date').value;
    const result = await json<{ rows: Row[] }>(`days/${day}.json`);
    if (request !== dayRequest) return;
    rows = result.rows;
    displayedDate = day;
    const provisional = day === index.provisional_date;
    $('price-heading').textContent = provisional ? '장중 가격 (잠정)' : '본장 종가';
    $('price-basis').textContent = provisional ? 'USD · 장중·잠정 기준' : 'USD · 본장 종가 기준';
    $('table-heading').textContent = provisional ? '시가총액 순위 · 장중·잠정' : '시가총액 순위';
    notice(provisional ? '장중·잠정 데이터입니다. 실시간 스트리밍이 아닌 수집 시점의 값이며, 종가·시가총액은 장 마감까지 바뀔 수 있습니다. 종가 이력에는 포함하지 않습니다.' : '');
    pageSize = 50;
    if (resetSelection) selected = new Set(rows.slice(0, Number($<HTMLSelectElement>('top').value)).map(r => r.instrument_id));
    $('asof-date').textContent = day.replaceAll('-', '.');
    $('stat-companies').textContent = number.format(rows.length);
    $('stat-cap').textContent = cap(rows.reduce((sum, r) => sum + r.market_cap_usd, 0));
    renderTable();
    await renderChart();
  } catch {
    if (request === dayRequest) {
      if (displayedDate) $<HTMLSelectElement>('date').value = displayedDate;
      notice('선택한 거래일의 데이터를 불러오지 못했습니다. 이전 화면을 유지합니다.');
    }
  }
}

function toggle(id: string) {
  if (selected.has(id)) selected.delete(id);
  else if (selected.size < 20) selected.add(id);
  else { notice('한 번에 최대 20개 종목을 비교할 수 있습니다. 선택한 종목을 해제한 뒤 추가하세요.'); return; }
  renderTable();
  void renderChart();
}

$('rows').addEventListener('click', event => {
  const target = (event.target as HTMLElement).closest<HTMLButtonElement>('[data-company]');
  if (target?.dataset.company) toggle(target.dataset.company);
});
$('selected').addEventListener('click', event => {
  const target = (event.target as HTMLElement).closest<HTMLButtonElement>('[data-company]');
  if (target?.dataset.company) toggle(target.dataset.company);
});
$('search').addEventListener('input', () => { pageSize = 50; renderTable(); });
$('more').addEventListener('click', () => { pageSize += 50; renderTable(); });
$('date').addEventListener('change', () => void loadDay());
$('period').addEventListener('change', () => void renderChart());
$('top').addEventListener('change', () => {
  selected = new Set(rows.slice(0, Number($<HTMLSelectElement>('top').value)).map(r => r.instrument_id));
  renderTable();
  void renderChart();
});

async function boot() {
  try {
    index = await json<Index>('index.json');
    if (index.schema_version !== 2) throw new Error('Unsupported data format');
    if (!index.dates.length) { showEmpty(); return; }
    const latest = index.dates.at(-1)!;
    $<HTMLSelectElement>('date').innerHTML = [...index.dates].reverse().map(d => `<option value="${escape(d)}">${escape(d)}${d === index.provisional_date ? ' · 장중·잠정' : ''}</option>`).join('');
    for (const id of ['date', 'search', 'top', 'period']) ($<HTMLInputElement>(id)).disabled = false;
    const closedDates = index.closed_dates ?? index.dates;
    $('stat-days').textContent = number.format(closedDates.length);
    $('history-range').textContent = closedDates.length ? `${closedDates[0]} — ${closedDates.at(-1)}` : '첫 장 마감 후 종가 기록 시작';
    const collectedAt = index.provisional_at ?? index.status.last_success_at;
    $('updated-at').textContent = collectedAt ? `${new Intl.DateTimeFormat('ko-KR', {
      timeZone: 'Asia/Seoul', dateStyle: 'short', timeStyle: 'short',
    }).format(new Date(collectedAt))} KST 수집` : '갱신 시각 확인 중';
    $('method-text').textContent = `${index.scope}. ${index.method}.`;
    if (!index.is_demo) $('method-text').textContent += ' 가격·주식수: Yahoo Finance, ETF 발행좌수 보완: TradingView, 한국어 이름·ADR 분류 보완: 한투 공개 종목 명부. 한투 앱과 시세·발행수 갱신 시점이 달라 순위가 다를 수 있습니다.';
    $('source').textContent = `${index.is_demo ? 'FICTIONAL DEMO' : 'YAHOO · TRADINGVIEW · KIS 명부'} · USD`;
    const messages = [];
    if (index.is_demo) messages.push('데모 미리보기 — 가상 종목과 합성 데이터입니다. 실제 주가·시가총액이 아닙니다.');
    if (index.status.state === 'error') messages.push('최근 갱신에 실패하여 마지막 정상 데이터를 표시합니다.');
    if (index.status.state === 'incomplete') messages.push('일부 과거 거래일의 원본이 없어 이력에 빈 구간이 있습니다. 확인된 거래일만 표시합니다.');
    if (index.coverage) {
      const coverage = index.coverage;
      const excluded = coverage.excluded_quotes?.length ?? 0;
      messages.push(`대상 명부 ${number.format(coverage.directory_eligible)}개 티커 중 ${number.format(coverage.rankable_tickers ?? coverage.quoted_eligible)}개를 검증했습니다. 미제공 ${number.format(coverage.unquoted_tickers.length)}개, 가격·시총 미검증 ${number.format(excluded)}개는 순위에서 제외됩니다.`);
      if (coverage.by_type) messages.push(Object.entries(coverage.by_type).map(([kind, value]) => `${kind === 'CS' ? '보통주' : kind} ${number.format(value.ranked)}개`).join(' · ') + '를 각각 순위에 포함합니다.');
      if (coverage.stale_quote_tickers?.length) messages.push(`당일 체결이 없는 ${number.format(coverage.stale_quote_tickers.length)}개 티커는 마지막 체결일을 가격 옆에 표시합니다.`);
    }
    if (index.status.expected_trade_date && latest < index.status.expected_trade_date)
      messages.push(`아직 ${index.status.expected_trade_date} 거래일 데이터가 준비되지 않았습니다.`);
    if (!index.is_demo && index.status.attempted_at && Date.now() - Date.parse(index.status.attempted_at) > 4 * 86400000)
      messages.push('최근 갱신 확인이 오래되었습니다. 표시된 기준 거래일을 확인해 주세요.');
    baseNotice = messages.join(' ');
    notice('');
    const download = $<HTMLAnchorElement>('download');
    download.textContent = index.provisional_date ? '장중·잠정 순위 CSV ↗' : '최신 순위 CSV ↗';
    download.href = './data/latest-rankings.csv'; download.download = 'latest-rankings.csv'; download.hidden = false;
    await loadDay(true);
  } catch {
    showEmpty();
    notice('데이터를 불러올 수 없습니다. 첫 수집이 완료되었는지 확인하거나 잠시 후 다시 방문해 주세요.');
  }
}

function showEmpty() {
  $('updated-at').textContent = '아직 수집된 거래일이 없습니다';
  $('rows').innerHTML = '<tr><td colspan="6" class="empty-cell">첫 거래일 데이터가 준비되면 종목별 순위가 표시됩니다.</td></tr>';
  $('stat-days').textContent = '0';
}

void boot();
