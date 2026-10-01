# MarketCap Ranking

미국 상장 기업의 본장 종가와 시가총액 순위를 매일 기록하고, 날짜별 순위 변화를 보여줍니다. 한 기업에 여러 티커를 연결하며 각 티커의 종가는 개별 저장합니다.

**데이터는 Yahoo Finance의 일괄 조회와 Nasdaq의 공개 종목 명부를 사용합니다. API 키와 유료 구독은 필요하지 않습니다.** Massive 연동은 제거했으며, 기존 `.env` 파일과 그 안의 키는 사용하거나 변경하지 않습니다.

Python 3.12 수집기, 날짜별 CSV·JSON 저장, TypeScript·Vite·Apache ECharts 화면, GitHub Actions 예약 실행과 GitHub Pages 배포로 구성합니다.

## 기본 동작: 전체 후보의 시가총액 순위 기록

`python download.py` 또는 `marketcap collect`를 실행하면 종목을 자동으로 찾고 다음을 수행합니다. 고정 티커 목록이나 상위 N개 제한을 두지 않습니다.

1. NYSE·Nasdaq·NYSE American에 대한 Yahoo 응답을 250개씩 **마지막 페이지까지** 조회합니다.
2. Nasdaq 공개 명부와 대조해 대상 보통주를 골라 본장 종가·시가총액·날짜를 검증합니다.
3. 같은 기업의 여러 티커를 연결하고 기업 시가총액을 한 번씩 계산합니다.
4. 시가총액 내림차순으로 **확인된 기업 전체**의 순위를 저장합니다. 상위 10·20개 선택은 그래프 표시 옵션이며 저장 수 제한이 아닙니다.
5. 날짜별 `rankings.csv`, 모든 대상 티커의 `prices.csv`와 기업별 순위 이력을 누적합니다.

조회 도중 순서가 바뀌어 종목이 중복·누락되지 않도록 API 페이지는 티커 순으로 읽고, 전체 응답을 받은 뒤 기업 시가총액 순으로 정렬합니다. 종목이 추가되면 다음 수집에서 자동으로 포함됩니다.

## 로컬 실행

Python 3.12와 Node.js 22를 사용합니다. Ubuntu에서 venv 생성이 실패하면 `python3.12-venv` 패키지를 설치하세요.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .

# 요청 수를 제한한 실제 연결 확인. 순위를 게시하지 않습니다.
marketcap probe

# 전체 대상의 종가·시가총액·순위: 본장 종료 후, 다음 본장 시작 전에 실행
python download.py
marketcap export

cd web
npm ci
npm run dev
```

`probe`는 Yahoo의 첫 페이지에서 3개 종목만 가져오고, 실제 HTTP 요청 수와 응답을 `data/probe.json`에 기록합니다. 장중 응답도 연결 검증 보고서에만 기록하며, 종가 순위로 사용하지 않습니다.

화면을 먼저 확인하려면 별도의 가상 데이터를 사용합니다.

```bash
marketcap demo
marketcap export --data-dir demo-data
cd web
npm ci
npm run dev
```

가상 기업 24개·티커 26개의 약 1년 기록입니다. 화면에 **가상 데이터** 표시가 나오며 실제 수집의 대체 데이터로 자동 사용하지 않습니다. 실데이터로 돌아갈 때는 `marketcap export --data-dir data`를 실행합니다. 원본 디렉터리에는 서로 다른 공급자의 기록을 섞을 수 없습니다.

## 무료 수집 방식과 범위

Yahoo screener는 최대 250개씩 조회합니다. 전체 대상 페이지를 모두 받은 뒤 Nasdaq 명부와 대조합니다. 개별 기업마다 HTTP 요청을 보내지 않습니다. 실제 확인 당시 Yahoo의 해당 거래소 조회 결과는 약 7,400개 티커였으며, 같은 규모라면 약 30개 페이지와 명부 2회, 인증·쿠키 요청이 필요합니다. 종목 수는 매일 달라집니다.

`config/settings.json`의 기본 제한은 **분당 20회, 명령 실행당 HTTP 요청 최대 80회**입니다. 이 수치는 프로그램의 자체 제한이며 Yahoo가 보장하는 무료 할당량이 아닙니다. yfinance의 쿠키·인증 요청도 포함해 제한합니다. 429 응답에는 빠른 반복 재시도를 하지 않고 중단합니다. Actions도 전체 종가·순위를 한 번의 일괄 수집으로 기록하므로 같은 80회 상한을 적용합니다. 보조 기능인 과거 종가 다운로드만 티커별 요청을 사용합니다. Yahoo Finance는 공식적인 무제한 API나 가용성 보장이 없으므로 일시적인 차단·응답 형식 변경은 있을 수 있습니다.

대상은 NYSE, Nasdaq, NYSE American의 USD 일반주식 중 다음 조건을 충족하는 종목입니다.

- Yahoo 주식 screener와 Nasdaq 명부 양쪽에서 확인되는 종목
- 명부에 Common Stock / Common Shares / Ordinary Shares / Capital Stock으로 명시된 종목
- 테스트 종목·ETF·ADR·예탁증권·우선주·워런트·유닛·채권·권리 등 제외
- 해당 거래일의 본장 가격·기업 시가총액이 확인되는 종목

미국 상장 여부가 기준이며 회사 국적은 필터링하지 않습니다. 명칭 기반 분류로 모든 상장 상품을 완벽히 분류할 수 있다는 보장은 없습니다. 명부에 있으나 Yahoo가 제공하지 않는 종목 수와 티커는 `coverage`에 기록하고 화면에도 제외 수를 표시합니다. 순위는 **이 공개 데이터에서 확인 가능한 범위 내 순위**입니다. 모든 미국 상장 기업이 누락 없이 포함된 공식 전 시장 순위로 해석하지 마세요.

전체 페이지 수가 맞지 않거나 중복 페이지·목록 변화가 감지되면 게시하지 않습니다. 가격·시총 누락이나 기준일 불일치가 있는 티커는 사유와 함께 `coverage/YYYY-MM-DD.json`의 `excluded_quotes`에 기록하며 순위에서 제외합니다. 명부 대비 검증된 티커 비율 `minimum_quote_coverage`(기본 98%), `minimum_companies`(기본 1,000), 직전 기록 대비 기업 수 비율(기본 90%)을 모두 충족해야 저장합니다. 이 값들은 상위 N개 필터가 아닙니다. 화면에도 누락 수를 표시합니다.


현재 전체 조회 범위를 확인하려면 장중에도 다음 명령을 사용할 수 있습니다.

```bash
marketcap inspect-universe
# 이미 받은 원본으로 다시 검증: 네트워크 요청 없음
marketcap inspect-universe --archive data/inspection/universe.json
```

`data/inspection/report.json`에 전체 조회 수·명부 수·검증 수·기업 수·제외 사유를, `rankings-preview.csv`에는 기업별 시가총액 정렬 결과를 저장합니다. `is_final_close=false`로 표시하며 이 결과는 일별 종가 이력이나 사이트에 게시하지 않습니다. 장중 시가총액을 전날 종가 시가총액으로 취급하지 않습니다.

## 장중·잠정 첫 화면

`marketcap collect --allow-provisional`은 NYSE 달력상 본장이 열린 동안 별도의 `provisional.json`을 갱신합니다. Actions는 이 옵션을 사용합니다. 장중 순위는 수집 시점의 값이며 실시간 스트리밍이 아닙니다. 화면과 CSV에 **장중·잠정**으로 표시하고 `snapshots/`, 종가 원본 `bundles/`, 확정 거래일 수와 기업별 그래프 이력에 포함하지 않습니다. 같은 날짜의 종가가 수집되면 확정 데이터가 자동으로 우선합니다.

거래가 드문 종목은 당일 체결이 없을 수 있습니다. 잠정 화면은 최근 14일 이내의 마지막 체결 가격을 허용하되, 당일이 아니면 가격 옆에 체결일을 표시합니다. CSV에도 `quote_date`와 `is_final_close=False`를 기록하고 가격 컬럼은 `price`를 사용합니다. 가격·시총 누락, 미래 시각, 14일 초과 가격은 제외하며 98% 명부 검증 기준은 그대로 적용합니다. 확정 종가는 기존대로 대상 거래일의 가격만 허용합니다.

전일 종가 자체는 `download-closes`로 검증할 수 있지만 현재 시총으로 전일 시총을 역산해 게시하지 않습니다. 수집 전 날짜의 시총 순위는 공백으로 남습니다.

## 기업·티커·시가총액 기준

1. 기업명에서 명시적인 주식 클래스 접미사만 제거한 뒤 **정확히 같은 이름**을 묶습니다. 이름 유사도에 의한 병합은 하지 않습니다.
2. 최초 기업 ID는 정규화한 기업명 해시입니다. 이후 기존 티커의 기업 ID를 유지하고, 이미 기록된 기업명의 새 티커도 같은 기업에 연결합니다.
3. 서로 다른 회사가 같은 이름을 쓰거나 기업명·티커가 동시에 바뀌는 경우 `identity_overrides`로 명시적인 연결을 지정해야 합니다. 이 ID는 CIK·LEI 같은 공인 기업 식별자를 대체하지 않습니다.
4. `canonical_tickers`에 기업 ID 또는 기업명으로 대표 티커를 설정할 수 있습니다. 기본값은 Alphabet `GOOGL`, Berkshire Hathaway `BRK-B`입니다. 설정이 없으면 안정적인 증권 ID 순으로 선택합니다.
5. **대표 티커의 Yahoo `marketCap`을 기업 시가총액으로 한 번만 저장**합니다. 같은 기업의 다른 티커 시가총액을 더하지 않습니다. 공급자가 제공하는 기업 가치의 클래스 환산 방식에 따라 다른 서비스와 차이가 날 수 있습니다.

수동 식별자 설정 예시:

```json
{
  "identity_overrides": {
    "EXAMPLE-A": {"company_id": "manual:example", "security_id": "manual:example-a"},
    "EXAMPLE-B": {"company_id": "manual:example", "security_id": "manual:example-b"}
  }
}
```

기존 설정 파일의 해당 항목에 병합합니다. 주가에는 장 종료 후 Yahoo `regularMarketPrice`를 사용하고 `regularMarketTime`의 뉴욕 날짜가 대상 거래일인지 검증합니다. `marketState=REGULAR` 응답은 거부합니다. 시간외 가격과 수정주가를 사용하지 않습니다. 가격과 시가총액은 같은 응답 묶음에서 가져옵니다. 시가총액 자체에는 별도 거래일 필드가 없어 본장 종료 후의 동일 quote에서 제공된 값이라는 기준을 적용합니다.

순위는 Decimal 금액을 USD 센트 단위로 저장한 뒤 내림차순으로 계산합니다. 같은 금액은 `1, 2, 2, 4` 공동순위이며 화면의 조·억 단위 반올림은 순위에 영향을 주지 않습니다. 순위 변동은 직전 **미국 거래일**과 비교하고 신규 기업은 `NEW`, 기준일·누락 구간은 비교 불가로 표시합니다.

## 날짜별 기록과 과거 복구

기록은 수집을 시작한 시점부터 쌓입니다. **현재 시가총액이나 현재 주식수로 수집 전 과거의 시가총액을 복원하지 않습니다.** Yahoo의 이 무료 일괄 경로에는 신뢰할 수 있는 과거 기업 시가총액·당시 전체 종목 목록이 없습니다.

```text
data/
  status.json
  probe.json                       # 소수 종목 연결 검증; 순위 데이터와 분리
  coverage/YYYY-MM-DD.json          # 수집 범위·누락 티커와 사유
  bundles/YYYY-MM-DD.json           # 그날 캡처한 전체 quote·명부 원본
  pending/<거래일>/<정책 해시>/      # 중단된 처리의 검증된 응답
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

웹 내보내기는 전체 기업의 `latest-rankings.csv`와 모든 티커의 `latest-prices.csv`를 제공합니다. 화면의 CSV 버튼은 순위 파일을 내려받습니다.

가격 CSV의 첫 세 컬럼은 요구한 순서입니다.

```text
company_name,ticker,close,trade_date,company_id,security_id,currency,source,collected_at
```

`rankings.csv`에는 기업별 시가총액·순위·대표 티커·산정 방식·출처를 기록합니다. 과거 산식과의 스키마 호환을 위한 `weighted_shares_outstanding`은 Yahoo 경로에서 빈 값입니다. 기업·증권 연결은 각 거래일의 `securities.json`에 남깁니다.

휴장일에는 새 날짜를 만들지 않습니다. 서머타임과 조기 폐장은 NYSE 달력으로 처리합니다. 지원 거래소의 일반 주식 세션은 같은 달력을 사용합니다. 원본 묶음이 남아 있는 누락일은 다음 실행에서 복구하고, **원본 자체를 수집하지 못한 날짜는 `unrecoverable_dates`로 보고하며 그래프에도 빈 구간을 유지**합니다. 이때 최신 거래일의 검증된 데이터는 저장할 수 있지만 실행 결과는 불완전 상태로 남깁니다.

```bash
# 저장된 원본으로 과거 기간을 다시 처리
marketcap collect --from 2026-09-01 --to 2026-09-30 --refresh

# 별도 디렉터리 사용
marketcap collect --data-dir records --settings config/settings.json
marketcap export --data-dir records --output web/public/data
```

`--refresh`는 저장된 closing bundle을 재처리합니다. 현재 quote로 과거를 덮어쓰지 않습니다. 같은 데이터는 중복 생성하지 않고 변경된 결과는 새 리비전에 보존합니다. 완성된 파일 묶음을 작성한 뒤 포인터를 교체하며, 수집 실패 시 이전 정상 기록을 유지합니다. 순위 변동은 내보낼 때 재계산합니다. 임시 SQLite를 사용해 모든 날짜의 원본을 메모리에 올리지 않고 기업별 시계열 파일을 만듭니다.

대상 범위·기업 식별·대표 티커 정책 변경은 기존 순위와 섞이지 않도록 거부합니다. 변경하려면 원본을 보존한 별도 디렉터리에서 정책에 맞춰 이력을 다시 생성하세요.

## 선택 기능: 개별 종목의 과거 종가

[`syuka-fan/stock`](https://github.com/syuka-fan/stock)의 `download.py`와 `symbols.json` 구조를 참고했습니다. yfinance로 일봉을 받아 종목별 CSV에 병합하고, 재실행할 때 마지막 저장일보다 7일 앞에서 다시 조회합니다. 참고 버전은 `568d4f8b86027d56e2b97f6a186f9b91f45fd029`이며 출처와 MIT 라이선스는 `THIRD_PARTY_NOTICES`에 기록했습니다.

이 명령은 과거 가격을 별도로 조사할 때만 사용합니다. 일별 순위 수집과 Actions는 이 목록을 사용하지 않습니다. API 키는 필요하지 않습니다.

```bash
# 설정된 8개 티커 다운로드: 처음에는 1990-01-01부터 제공되는 이력
marketcap download-closes

# 소수 종목·기간으로 실행. 종료일은 포함하며 미완료 미국 거래일은 제외
marketcap download-closes --tickers AAPL,MSFT,GOOG,GOOGL --start 2026-09-01 --end 2026-09-30

# 이후에는 마지막 저장일 - 7일부터 증분 다운로드
marketcap download-closes --tickers AAPL,MSFT,GOOG,GOOGL

# 같은 기능의 설치형 명령, 다른 목록과 저장 폴더 사용
marketcap download-closes --symbols config/symbols.json --data-dir data

# 보관 중인 전체 기간 재조회 / 더 오래된 이력 추가
marketcap download-closes --refresh
marketcap download-closes --start 1990-01-01
```

`config/symbols.json`의 `us` 항목에 `"티커": "기업명"`을 추가합니다. 참고 저장소의 `symbols.json`을 `--symbols`에 지정해도 `us` 항목만 읽습니다. 기본 목록은 Apple, Microsoft, NVIDIA, Amazon, Alphabet의 GOOG·GOOGL, Berkshire의 BRK-A·BRK-B입니다. **이 8개 티커는 종가 이력 다운로드용 예시 목록이며, 시가총액 순위의 전체 대상 범위와는 별개**입니다. 미국 거래소의 USD 주식·ETF만 허용하며 `BRK.B`는 Yahoo 표기인 `BRK-B`로 적습니다.

```text
data/
  us_daily/AAPL.csv
  us_daily/GOOG.csv
  us_daily/GOOGL.csv
  download_state.json       # 티커별 첫날·마지막날·행 수
  download_status.json      # 요청 수·성공·실패·요청 제한으로 생략한 티커
```

CSV는 다음 순서이며 날짜 오름차순으로 저장합니다.

```text
company_name,ticker,close,trade_date,open,high,low,volume,stock_splits,currency,source
```

- NYSE 거래일 달력으로 서머타임·휴장·조기 폐장을 처리하고, 실행 시각에 이미 종료된 본장 일봉만 남깁니다. `prepost=False`, `auto_adjust=False`로 요청하며 `Adj Close`를 종가로 대체하지 않습니다.
- **Yahoo의 과거 `Close`는 주식분할을 소급 반영한 값**입니다. 배당을 반영하는 `Adj Close`와도, 분할 전 당시 화면에 표시됐던 가격과도 다를 수 있습니다. 수집기의 자동 보정은 끄지만 공급자가 적용한 분할 조정까지 제거하는 것은 아닙니다.
- 겹치는 기간의 종가가 달라지거나 새 분할이 있으면 보관한 전체 기간을 다시 받아 조정 기준을 맞춥니다. 행 수·마지막 날짜가 같아도 가격 정정을 반영합니다. 오래된 기타 정정은 `--refresh`로 다시 받습니다.
- 같은 날짜는 마지막 응답으로 병합하고 파일을 원자적으로 교체합니다. 티커 하나가 실패하면 그 티커의 기존 CSV를 유지하고 나머지는 계속 처리합니다. 요청 한도나 HTTP 429를 만나면 후속 요청을 중단합니다. 실패·생략이 있으면 종료 코드는 1입니다.
- 상태 파일이 없어지거나 손상되면 기존 CSV의 마지막 날짜에서 재개합니다. 이력 CSV로 과거 시가총액을 만들어 내지는 않습니다.

## GitHub Actions

1. 소스를 저장소 기본 브랜치에 커밋·푸시합니다.
2. **Settings → Pages → Source**를 **GitHub Actions**로 선택합니다. API secret은 필요하지 않습니다.
3. `main`에 푸시하면 **Update market rankings**가 자동 실행됩니다. 수동 **Run workflow**도 가능합니다. 장중에는 명시적으로 표시한 잠정 순위를 게시하고, 장 마감 후에는 확정 종가를 수집합니다.
4. 전체 대상의 종가 CSV·기업별 순위·수집 상태는 `data` 브랜치에 보관되고 순위 사이트는 Pages에 배포됩니다. 고정 목록의 과거 가격 다운로드는 예약 작업에 포함하지 않습니다.

```yaml
schedule:
  - cron: '0,20 9 * * 2-6'
    timezone: Asia/Seoul
```

한국 시간 화~토 09시와 09시 20분에 실행합니다. 두 번째 실행은 재확인이며, 이미 저장된 종가는 API 재조회나 중복 저장 없이 유지합니다. UTC 표현은 `0,20 0 * * 2-6`입니다. 미국 본장 종료 시각은 통상 한국 시간 다음 날 05시(서머타임) 또는 06시입니다. 09시는 **실행 예약**이며 완료 시각 보장은 아닙니다. GitHub 예약 실행은 지연·누락될 수 있고 공개 저장소는 60일 비활동 시 비활성화될 수 있습니다.

수집에는 `contents: write`, 배포에는 `pages: write`와 `id-token: write` 권한을 사용합니다. 조직 정책·브랜치 보호 규칙은 `data` 브랜치에 대한 봇의 쓰기를 허용해야 합니다. 데이터는 cache나 만료되는 artifact가 아닌 별도 브랜치에 영구 보관합니다. 강제 종료되면 아직 커밋하지 못한 원본은 사라질 수 있습니다.

매 실행마다 날짜·기업/티커 중복·시총 정렬·공동순위·CSV 일치·잠정/확정 이력 분리를 검사합니다. Pages 배포 후에도 공개 URL을 조회해 해당 실행의 publication_id와 일치하는지 확인합니다. 수집 실패 시 마지막 정상 데이터가 있으면 실패 상태와 함께 배포하고 workflow는 실패로 보고합니다. 첫 수집부터 실패해 정상 데이터가 전혀 없으면 빈 사이트를 새로 게시하지 않습니다. 빌드·배포 자체가 실패하면 기존 사이트가 유지됩니다. 마지막 시도가 4일 넘게 오래되면 화면에 갱신 지연을 표시합니다. 작업 제한 시간은 30분입니다. 원본이 커지면 저장소 크기를 모니터링하고 객체 저장소로 이전하는 것이 좋습니다.

Yahoo/yfinance는 개인적 이용을 전제로 합니다. 공개 사이트에 재배포하는 범위는 데이터 제공자의 이용 조건을 확인해야 합니다. 자동화 코드가 데이터 재배포 권한을 부여하는 것은 아닙니다.

## 검증

```bash
source .venv/bin/activate
ruff check src tests scripts download.py
ruff format --check src tests scripts download.py
pytest
marketcap demo
marketcap export --data-dir demo-data
cd web
npm ci
npm run build
npx playwright install chromium
npm test
```

CI도 같은 검사를 수행합니다. 달력·복수 티커·주식분할·중복 실행·정정 이력·날짜 불일치·과거 원본 부재·요청 예산·data 브랜치 저장·종가 증분 다운로드·장중 일봉 제외·부분 실패 보존을 검증합니다. Chromium에서는 검색·복수 티커·거래일 전환·실패 표시·빈 화면·모바일 화면을 확인합니다.

참고: [yfinance 일괄 screener](https://ranaroussi.github.io/yfinance/reference/api/yfinance.screen.html), [yfinance 프로젝트와 이용 범위](https://github.com/ranaroussi/yfinance), [Nasdaq 종목 명부 정의](https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs), [GitHub 예약 실행](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).
