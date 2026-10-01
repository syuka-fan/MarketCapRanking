# MarketCap Ranking

미국 상장 종목의 시가총액과 본장 종가를 기록하는 GitHub Pages 사이트입니다. **보통주·ADR·ETF를 포함하고, 티커마다 독립된 순위를 계산합니다.** 알파벳 A(GOOGL)·C(GOOG), 버크셔 A·B도 별도 행과 별도 이력으로 표시합니다.

사이트: https://syuka-fan.github.io/MarketCapRanking/

순위 그래프는 상위 **10·20·30·40·50개**를 선택하거나 개별 종목을 최대 50개까지 비교할 수 있습니다. 종목 수에 맞춰 그래프 높이를 조절하고, 색상·선 모양과 종목 이름의 마우스/키보드 강조로 구분합니다. 긴 선택 목록과 거래일 상세 정보는 내부 스크롤로 확인합니다.

## 순위 산정

`티커별 시가총액 = 해당 티커 본장 가격 × 해당 티커 발행 주식수(ADR 수량 / ETF 좌수)`

- 가격은 Yahoo의 `regularMarketPrice`, 보통주·ADR의 발행수는 TradingView의 티커별 `total_shares_outstanding_current`를 우선 사용합니다. 누락되면 Yahoo의 `sharesOutstanding`으로 보완합니다. 회사 전체를 환산한 `marketCap`, `impliedSharesOutstanding`은 순위 산식에 사용하지 않습니다.
- ETF 좌수는 TradingView의 ETF 전용 `shares_outstanding` 일괄 응답을 우선 사용하고, 없는 종목은 Yahoo가 제공한 해당 ETF의 `sharesOutstanding`을 사용합니다. 펀드 전체 순자산인 `netAssets`로 대신 계산하지 않습니다.
- ADR의 발행수에 예탁 비율을 다시 곱하지 않습니다. USD로 거래되는 예탁증권 단위의 가격·수량으로 계산합니다.
- 금액은 Decimal로 계산해 USD 센트 단위로 저장합니다. 같은 금액은 `1, 2, 2, 4` 공동순위입니다. 화면 표시용 반올림은 순위에 영향을 주지 않습니다.
- 기업 식별자는 참고 메타데이터입니다. 순위·가격·그래프의 기본키는 개별 증권의 `instrument_id`이며 기업 단위로 합치거나 대표 티커를 고르지 않습니다.

한국투자증권 앱의 ‘실시간 랭킹 → 미국 시가총액’과 비교해 티커별 계산 방식을 검증했습니다. 가격 공급원은 Yahoo이며 한투 실시간 시세 API에 직접 연결하지 않습니다. 가격·발행수 갱신 시점과 확인 가능한 종목 범위가 달라 한투 화면과 매 순간 동일한 순위를 보장하지는 않습니다. 사이트는 수집 시각을 표시하는 정적 페이지입니다.

## 수집 범위와 검증

NYSE·Nasdaq·NYSE American·NYSE Arca·Cboe BZX의 USD 보통주, ADR, ETF가 대상입니다. 미국 상장 여부가 기준이며 기업 국적을 제한하지 않습니다. 테스트 종목·우선주·워런트·유닛·채권·ETN·권리는 제외합니다.

1. Yahoo 주식 및 ETF screener를 티커 순으로 **마지막 페이지까지** 읽습니다. 고정 티커 목록이나 상위 N개 저장 제한이 없습니다.
2. Nasdaq 공개 종목 명부의 거래소·ETF 표시·종목명과 대조합니다. 한국투자증권 공개 종목 마스터로 한국어 이름과 ADR 여부를 보완합니다. 마스터 파일은 시세나 시가총액 공급원이 아닙니다.
3. TradingView 주식·ADR·ETF screener의 전체 페이지에서 티커별 발행수와 ETF 상장좌수를 받아 가격과 연결합니다. 응답 원본은 가격 원본과 함께 보관합니다. 주식수·좌수는 수집 당시 공급자가 제공한 값이며 별도 공시 기준일이 제공되지 않을 수 있습니다.
4. 가격·수량·통화·거래 시각을 검증한 티커 전체를 순위에 포함합니다. 누락 티커와 사유는 `coverage`에 남기고, 화면에 보통주·ADR·ETF별 포함 수와 전체 제외 수를 표시합니다.

전체 가격 응답은 명부 대비 **98% 이상**을 확보해야 하며 중복/불완전 페이지는 거부합니다. 장중 순위는 유효 티커 98% 이상, 종가 순위는 해당 거래일의 종가·발행수가 확인된 티커 **90% 이상**(`minimum_closing_quote_coverage`), 최소 **1,000개**, 직전 기록 대비 **90% 이상**을 요구합니다. 미체결·미제공 종목은 날짜별로 제외하고, 포함 비율이 98% 미만이면 화면에 일부 종목만 확인된 순위임을 표시합니다. 무료 공개 데이터에서 확인 가능한 범위의 순위이며 누락 없는 공식 전 시장 순위는 아닙니다.

`config/settings.json`은 자체 요청 제한을 분당 20회, 실행당 최대 180회로 설정합니다. 보통주·ADR·ETF 및 발행수 보완을 포함한 정상 수집은 확인 당시 약 77회였으며, 총 한도에는 목록 변동에 따른 재시도 여유를 포함합니다. Yahoo의 쿠키·인증과 보조 데이터 요청도 함께 셉니다. 429 응답에는 즉시 중단하며 빠른 재시도를 하지 않습니다. 조회 도중 주식/ETF 목록이 바뀌면 영향을 받은 screener만 최대 3회 다시 읽되 같은 요청 예산을 지킵니다. 장중 Yahoo 총수의 1% 이내 변동은 마지막 페이지까지 읽은 후 최종 건수와 중복 여부를 검증합니다. 공급자가 보장하는 할당량이나 가용성은 아닙니다.

## 종가와 장중 데이터

- 기본 실행은 **가장 최근에 마감된 미국 거래일 하루의 종가를 매번 다시 조회**합니다. 이미 저장된 날짜도 정정을 반영하며, 동일한 결과를 중복 저장하지 않습니다. 주말·휴장일·장중에는 직전 마감일을 대상으로 합니다. 과거 날짜 보충은 명시적으로 기간을 지정할 때만 실행합니다.
- 종가 수집은 현재 명부의 전체 보통주·ADR·ETF를 대상으로 합니다. 날짜가 확인되는 본장 가격 또는 직전 본장 종가를 우선 사용하고, 누락 종목은 Yahoo 일봉 API로 20개씩 조회합니다. 장중·시간외 값과 아직 마감되지 않은 날짜는 제외합니다. 현재 명부 기준이므로 과거에 상장폐지된 종목까지 복원하는 자료는 아닙니다.
- 본장 타임스탬프가 오래됐거나 마감 시각을 벗어나도 해당 거래일의 일봉 종가를 별도로 확인한 경우에는 그 가격을 사용합니다. 발행수는 같은 마감 후~다음 본장 시작 전 수집분만 연결하고, 가격과 발행수의 수집 근거를 마감 원본에 함께 보관합니다. 과거 2주 가격을 오늘 발행수와 연결하지 않습니다.
- `--allow-provisional`은 마지막 마감일 종가를 먼저 수집한 뒤 본장이 열린 동안 `provisional.json`도 갱신합니다. 화면과 CSV에 **장중·잠정**으로 표시하며 확정 거래일 수와 종가 그래프에 넣지 않습니다.
- 잠정 화면은 최근 14일 이내의 마지막 체결을 허용합니다. 당일 체결이 아니면 가격 옆과 CSV의 `quote_date`에 체결일을 표시합니다. 확정 종가는 해당 거래일의 가격만 허용합니다.
- 과거 종가는 시가총액·순위와 독립적으로 `closing-prices/`에 보관하고 사이트의 **전체 종목 종가 이력 CSV**로 제공합니다. 일봉 가격은 Yahoo의 주식분할 소급 조정이 적용될 수 있으며, 가격 기준은 각 행에 기록합니다. 미제공 날짜는 채워 넣지 않고 `close-status.json`에 날짜별 누락 종목을 기록합니다.
- 당시 발행주식수가 확인되는 마감 원본이 있는 경우만 과거 시가총액·순위로 저장합니다. 현재 발행수를 과거 종가에 곱해 순위를 만들지 않습니다. NYSE 달력으로 휴장일·서머타임·조기 폐장을 처리하고, 시총 원본이 없는 날짜는 `unrecoverable_dates`와 그래프 공백으로 남깁니다.

전체 종목의 최근 2주 종가를 한 번 보충하는 예시입니다. 아래 기간에는 마감된 10개 거래일이 있습니다. 이후 날짜를 생략한 실행은 마지막 마감일 하루만 갱신합니다.

```bash
marketcap collect-closes --data-dir data/ticker-v2 --from 2026-09-17 --to 2026-09-30 --max-requests 800
marketcap collect --data-dir data/ticker-v2 --allow-provisional
marketcap export --data-dir data/ticker-v2
```

보충 수집이 중단되면 같은 기간에 `--resume`을 붙여 저장된 요청부터 이어갑니다. `--archive <bundle.json>`은 보충 수집의 종목 명부를 고정할 때만 사용합니다. 일상 실행에는 둘 다 사용하지 않습니다. 2주치 전체 수집은 분당 20회 속도를 유지하며 약 30분이 걸리고, 명시적인 `--max-requests 800`은 해당 실행의 총 요청 한도만 늘립니다.

## 로컬 실행

Python 3.12와 Node.js 22를 사용합니다. API 키·유료 구독은 필요하지 않으며 기존 `.env`는 읽거나 변경하지 않습니다.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .

marketcap probe
marketcap collect --data-dir data/ticker-v2 --allow-provisional
marketcap export --data-dir data/ticker-v2
cd web
npm ci
npm run dev
```

`python download.py`는 `marketcap collect`와 같습니다. `probe`는 소수 quote로 연결만 확인합니다. 전체 범위 조사와 보관 원본 재검증은 다음 명령을 사용합니다.

```bash
marketcap inspect-universe --data-dir data/ticker-v2
marketcap inspect-universe --archive data/ticker-v2/inspection/universe.json
```

가상 기업 24개의 **26개 티커를 각각 순위로 계산한** 약 1년의 수집·내보내기 테스트 데이터도 제공합니다. 테스트 출력은 별도 경로에 보관하며, 웹에서 사용하는 `web/public/data`에는 실제 수집 데이터만 내보냅니다.

```bash
marketcap demo --data-dir demo-data/ticker-v2
marketcap export --data-dir demo-data/ticker-v2 --output demo-data/site
```

## 데이터 보관과 스키마

버전 2는 티커별 순위입니다. 기존 기업 단위 버전 1과 섞지 않도록 Actions는 `data` 브랜치의 **`ticker-v2/`** 아래에 저장합니다. 이전 원본은 그대로 보존하며 새 정책의 종가 이력으로 가져오지 않습니다. 로컬에서도 기존 데이터와 다른 디렉터리를 지정하세요.

```text
ticker-v2/
  status.json
  close-status.json
  closing-prices/YYYY-MM-DD.json
  closing-prices/revisions/<거래일>/<내용 SHA-256>.json
  close-requests/<시작일>_<종료일>/<배치 해시>.json
  provisional.json
  provisional-bundle.json
  coverage/YYYY-MM-DD.json
  bundles/YYYY-MM-DD.json
  pending/<거래일>/<정책 해시>/
  snapshots/YYYY-MM-DD/
    current.json
    revisions/<내용 SHA-256>/
      snapshot.json
      securities.json
      prices.csv
      rankings.csv
      raw.json.gz
      complete.json
```

가격 CSV의 앞 세 컬럼은 `company_name,ticker,close`입니다. 잠정 CSV는 `close` 대신 `price`를 쓰고 `is_final_close=False`를 기록합니다. 순위 CSV에는 티커·유형·시가총액·발행수·발행수 출처·순위·산식을 포함합니다. 웹에는 `latest-rankings.csv`, `latest-prices.csv`, 티커별 `instruments/*.json`을 내보냅니다.

완성된 파일을 작성한 뒤 포인터를 교체합니다. 같은 입력은 중복 저장하지 않고, 정정은 새 리비전으로 남깁니다. `--refresh`는 보관한 원본으로 재처리하며 오늘 데이터로 과거를 덮어쓰지 않습니다. 공급원이나 산정 정책이 바뀌면 기존 이력과 혼합을 거부합니다.

## 별도 과거 종가 다운로드

```bash
marketcap download-closes --tickers AAPL,MSFT,GOOG,GOOGL --start 2026-09-01 --end 2026-09-30
marketcap download-closes --tickers AAPL,MSFT,GOOG,GOOGL
```

`config/symbols.json` 목록은 이 보조 기능에만 사용하며 순위 수집 범위를 제한하지 않습니다. `data/us_daily/<ticker>.csv`에 저장하고 마지막 기록 7일 전부터 겹쳐 받아 가격 정정을 반영합니다. 진행 중인 미국 거래일과 시간외 가격은 제외합니다. Yahoo 과거 `Close`는 주식분할을 소급 반영할 수 있으며, 이 가격만으로 과거 시총을 복원하지 않습니다. 실패한 티커의 기존 CSV는 유지합니다.

구조 참고: [`syuka-fan/stock`](https://github.com/syuka-fan/stock), 버전 `568d4f8b86027d56e2b97f6a186f9b91f45fd029`. 출처와 MIT 라이선스는 `THIRD_PARTY_NOTICES`에 기록했습니다.

## Actions와 Pages

Pages Source를 **GitHub Actions**로 설정합니다. `main` 푸시와 수동 실행으로 수집·검증·배포합니다. 데이터는 별도 `data` 브랜치에 보관합니다.

예약은 **한국 시간 화~토 09:00, 09:20**입니다. 두 번째 실행도 마지막 마감일 종가를 재조회하여 정정을 반영합니다. 이전 날짜는 다시 받지 않고 동일한 값은 중복 저장하지 않습니다. 수동 실행에서 `from_date`를 지정하면 과거 종가 보충에 필요한 실행당 요청 한도를 800회로 늘립니다. `resume_backfill`은 같은 기간의 중단된 보충 수집을 이어받습니다. GitHub 예약 실행은 지연되거나 누락될 수 있습니다.

```yaml
schedule:
  - cron: '0,20 9 * * 2-6'
    timezone: Asia/Seoul
```

매 배포마다 티커 중복·한 순위에 한 티커·가격×발행수 산식·정렬·공동순위·CSV 일치·잠정/종가 이력 분리를 검사합니다. 배포 후 공개 URL의 `publication_id`까지 대조합니다. 수집 실패 시 마지막 정상 데이터를 실패 상태와 함께 배포하고 workflow는 실패로 보고합니다. 정상 데이터가 전혀 없으면 빈 사이트로 덮어쓰지 않습니다.

## 개발 검증

```bash
ruff check src tests scripts download.py
ruff format --check src tests scripts download.py
pytest
marketcap demo --data-dir demo-data/ticker-v2
marketcap export --data-dir demo-data/ticker-v2 --output demo-data/site
python scripts/verify_site.py demo-data/site
cd web
npm ci
npm run build
npx playwright install chromium
npm test
```

CI는 티커별 계산·ADR/ETF 포함·발행수 누락·전체 페이지 조회·날짜·중복 실행·과거 원본 복구·실패 보존과 브라우저 검색·개별 티커 비교·모바일 화면을 검증합니다. 브라우저 테스트의 가상 데이터는 `web/tests/fixtures/market.ts`에서 요청 응답으로만 주입하며 실제 데이터 파일을 덮어쓰지 않습니다. 60개 가상 종목의 순위 교차·긴 이름·누락 이력으로 10~50개 비교, PC/모바일 너비, 상세 정보 스크롤, 단일 거래일을 확인하고 `web/test-results`에 화면 캡처를 남깁니다. 게시 workflow는 `is_demo: true`인 데이터를 거부합니다.

데이터 출처: [Yahoo/yfinance](https://github.com/ranaroussi/yfinance), [Nasdaq 공개 명부](https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs), [한투 종목 마스터 정의](https://github.com/koreainvestment/open-trading-api/blob/main/stocks_info/overseas_stock_code.py), [TradingView ETF 발행좌수 정의](https://www.tradingview.com/support/solutions/43000748391-shares-outstanding/). 공개 데이터 접근과 재배포에는 각 제공자의 이용 조건이 적용됩니다.
