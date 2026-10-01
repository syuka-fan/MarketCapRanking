"""Public instrument names/types and ETF units, archived with each price capture."""

import io
import re
import zipfile
from datetime import UTC, datetime

import httpx

from marketcap.models import DataError, positive

ETF_COLUMNS = ["name", "type", "subtype", "shares_outstanding", "currency", "exchange"]


def kis_rows(text: str) -> dict:
    result = {}
    for line in text.splitlines():
        row = [v.strip() for v in line.split("\t")]
        if len(row) != 24:
            raise DataError("KIS public instrument directory schema changed")
        if row[0] != "US" or row[9] != "USD" or row[8] not in {"2", "3"}:
            continue
        ticker = row[4].replace(".", "-").replace("/", "-")
        adr = row[17] == "Y" or re.search(r"\b(ADR|ADS)\b", row[6] + " " + row[7], re.I)
        result[ticker] = {
            "name": row[6],
            "english_name": row[7],
            "security_type": "ETF" if row[8] == "3" else "ADR" if adr else "CS",
        }
    if not result:
        raise DataError("KIS public instrument directory is empty")
    return result


def etf_units(bundle: dict) -> dict:
    if bundle.get("columns") != ETF_COLUMNS:
        raise DataError("ETF shares response schema changed")
    rows = bundle.get("data", [])
    if len(rows) != bundle.get("totalCount") or not rows:
        raise DataError("Incomplete ETF shares universe")
    symbols, result = set(), {}
    for row in rows:
        if row["s"] in symbols or len(row["d"]) != len(ETF_COLUMNS):
            raise DataError("Duplicate or invalid ETF shares row")
        symbols.add(row["s"])
        ticker, kind, subtype, shares, currency, exchange = row["d"]
        if kind != "fund" or subtype != "etf" or currency != "USD" or exchange == "OTC":
            continue
        if shares is None:
            continue
        shares = positive(shares, "ETF shares outstanding")
        ticker = ticker.replace(".", "-")
        if ticker in result:
            raise DataError(f"Ambiguous ETF ticker: {ticker}")
        result[ticker] = str(shares)
    return result


def fetch_supplements(budget, include_etf: bool) -> dict:
    def request(method, url, **kwargs):
        budget.acquire()
        try:
            response = httpx.request(method, url, timeout=30, **kwargs)
            if response.status_code == 429:
                budget.stop_reason = "Public supplement rate limit reached; stopping requests"
                raise DataError(budget.stop_reason)
            response.raise_for_status()
            return response
        except httpx.HTTPError:
            raise DataError("Public instrument/ETF supplement is unavailable") from None

    directories = {}
    for market in ("nas", "nys", "ams"):
        response = request(
            "GET", f"https://new.real.download.dws.co.kr/common/master/{market}mst.cod.zip"
        )
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            text = archive.read(f"{market.upper()}MST.COD").decode("cp949")
        kis_rows(text)
        directories[market] = text
    result = {"kis_directories": directories}
    if include_etf:
        # This is the ETF-specific units field. Company shares and fund AUM
        # are different concepts and cannot substitute for these units.
        rows, total = [], None
        while total is None or len(rows) < total:
            payload = {
                "filter": [
                    {"left": "type", "operation": "equal", "right": "fund"},
                    {"left": "subtype", "operation": "equal", "right": "etf"},
                ],
                "columns": ETF_COLUMNS,
                "sort": {"sortBy": "name", "sortOrder": "asc"},
                "range": [len(rows), len(rows) + 1000],
            }
            page = request(
                "POST", "https://scanner.tradingview.com/america/scan", json=payload
            ).json()
            count = page.get("totalCount")
            if not isinstance(count, int) or count <= 0 or (total is not None and count != total):
                raise DataError("ETF shares universe changed during pagination")
            total = count
            if not page.get("data"):
                raise DataError("ETF shares pagination ended early")
            rows.extend(page["data"])
        result["etf_shares"] = {
            "columns": ETF_COLUMNS,
            "totalCount": total,
            "data": rows,
            "captured_at": datetime.now(UTC).isoformat(),
            "source": "TradingView ETF shares outstanding",
        }
        etf_units(result["etf_shares"])
    return result
