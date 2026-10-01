# MarketCap Ranking

미국 상장 종목의 시가총액과 본장 종가를 기록하는 GitHub Pages 사이트입니다. **보통주·ADR·ETF를 포함하고, 티커마다 독립된 순위를 계산합니다.** 알파벳 A(GOOGL)·C(GOOG), 버크셔 A·B도 별도 행과 별도 이력으로 표시합니다.

사이트: https://syuka-fan.github.io/MarketCapRanking/

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

기본 검증 기준은 명부 대비 유효 티커 **98% 이상**, 최소 **1,000개**, 직전 기록 대비 **90% 이상**입니다. 기준에 못 미치거나 중복/불완전 페이지를 받으면 게시용 데이터를 저장하지 않습니다. 무료 공개 데이터에서 확인 가능한 범위의 순위이며 누락 없는 공식 전 시장 순위는 아닙니다.

`config/settings.json`은 자체 요청 제한을 분당 20회, 실행당 최대 80회로 설정합니다. Yahoo의 쿠키·인증과 보조 데이터 요청도 포함합니다. 429 응답에는 즉시 중단하며 빠른 재시도를 하지 않습니다. 조회 도중 주식/ETF 목록이 바뀌면 최대 3회 재시도하되 같은 요청 예산을 지킵니다. 장중 Yahoo 총수의 1% 이내 변동은 마지막 페이지까지 읽은 후 최종 건수와 중복 여부를 검증합니다. 공급자가 보장하는 할당량이나 가용성은 아닙니다.

## 종가와 장중 데이터

- 본장 종료 후부터 다음 본장 시작 전까지 최신 거래일의 종가를 수집합니다. 뉴욕 기준 거래일과 본장 타임스탬프를 확인하고 시간외 가격은 사용하지 않습니다.
- `--allow-provisional`은 본장이 열린 동안 `provisional.json`을 갱신합니다. 화면과 CSV에 **장중·잠정**으로 표시하며 확정 거래일 수와 종가 그래프에 넣지 않습니다.
- 잠정 화면은 최근 14일 이내의 마지막 체결을 허용합니다. 당일 체결이 아니면 가격 옆과 CSV의 `quote_date`에 체결일을 표시합니다. 확정 종가는 해당 거래일의 가격만 허용합니다.
- 전일 가격만으로 전일 전체 시가총액을 역산하지 않습니다. 종가 기록은 실제 장 마감 원본을 수집한 날부터 시작합니다.
- NYSE 달력으로 휴장일·서머타임·조기 폐장을 처리합니다. 누락한 과거 날짜에 보관 원본이 없으면 `unrecoverable_dates`로 보고하고 그래프에 공백을 남깁니다.

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

가상 기업 24개의 **26개 티커를 각각 순위로 계산한** 약 1년의 화면 테스트 데이터도 제공합니다. 실데이터 대신 자동 게시하지 않습니다.

```bash
marketcap demo --data-dir demo-data/ticker-v2
marketcap export --data-dir demo-data/ticker-v2
```

## 데이터 보관과 스키마

버전 2는 티커별 순위입니다. 기존 기업 단위 버전 1과 섞지 않도록 Actions는 `data` 브랜치의 **`ticker-v2/`** 아래에 저장합니다. 이전 원본은 그대로 보존하며 새 정책의 종가 이력으로 가져오지 않습니다. 로컬에서도 기존 데이터와 다른 디렉터리를 지정하세요.

```text
ticker-v2/
  status.json
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

예약은 **한국 시간 화~토 09:00, 09:20**입니다. 두 번째 실행에서 이미 저장된 종가가 있으면 API 재조회나 중복 저장 없이 보존 상태를 검증합니다. GitHub 예약 실행은 지연되거나 누락될 수 있습니다.

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
marketcap export --data-dir demo-data/ticker-v2
python scripts/verify_site.py web/public/data
cd web
npm ci
npm run build
npx playwright install chromium
npm test
```

CI는 티커별 계산·ADR/ETF 포함·발행수 누락·전체 페이지 조회·날짜·중복 실행·과거 원본 복구·실패 보존과 브라우저 검색·개별 티커 비교·모바일 화면을 검증합니다.

데이터 출처: [Yahoo/yfinance](https://github.com/ranaroussi/yfinance), [Nasdaq 공개 명부](https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs), [한투 종목 마스터 정의](https://github.com/koreainvestment/open-trading-api/blob/main/stocks_info/overseas_stock_code.py), [TradingView ETF 발행좌수 정의](https://www.tradingview.com/support/solutions/43000748391-shares-outstanding/). 공개 데이터 접근과 재배포에는 각 제공자의 이용 조건이 적용됩니다.
