"""Public instrument names/types and ETF units, archived with each price capture."""

import io
import re
import zipfile
from datetime import UTC, datetime

import httpx

from marketcap.models import DataError, positive

ETF_COLUMNS = ["name", "type", "subtype", "shares_outstanding", "currency", "exchange"]
STOCK_COLUMNS = [
    "name",
    "type",
    "subtype",
    "total_shares_outstanding_current",
    "currency",
    "exchange",
]


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


def _units(bundle: dict, columns: list, *, etf: bool) -> dict:
    if bundle.get("columns") != columns:
        raise DataError("Ticker shares response schema changed")
    rows = bundle.get("data", [])
    if len(rows) != bundle.get("totalCount") or not rows:
        raise DataError("Incomplete ticker shares universe")
    symbols, result = set(), {}
    for row in rows:
        if row["s"] in symbols or len(row["d"]) != len(columns):
            raise DataError("Duplicate or invalid ticker shares row")
        symbols.add(row["s"])
        ticker, kind, subtype, shares, currency, exchange = row["d"]
        supported = (
            (kind == "fund" and subtype == "etf")
            if etf
            else (kind == "dr" or (kind == "stock" and subtype == "common"))
        )
        if not supported or currency != "USD" or exchange == "OTC":
            continue
        if shares is None:
            continue
        shares = positive(shares, "ticker shares outstanding")
        ticker = ticker.replace(".", "-")
        if ticker in result:
            raise DataError(f"Ambiguous ticker: {ticker}")
        result[ticker] = str(shares)
    return result


def etf_units(bundle: dict) -> dict:
    return _units(bundle, ETF_COLUMNS, etf=True)


def stock_units(bundle: dict) -> dict:
    return _units(bundle, STOCK_COLUMNS, etf=False)


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

    def fetch_units(columns, filters):
        rows, total = [], None
        while total is None or len(rows) < total:
            payload = {
                "filter": filters,
                "columns": columns,
                "sort": {"sortBy": "name", "sortOrder": "asc"},
                "range": [len(rows), len(rows) + 1000],
            }
            page = request(
                "POST", "https://scanner.tradingview.com/america/scan", json=payload
            ).json()
            count = page.get("totalCount")
            if not isinstance(count, int) or count <= 0 or (total is not None and count != total):
                raise DataError("Ticker shares universe changed during pagination")
            total = count
            if not page.get("data"):
                raise DataError("Ticker shares pagination ended early")
            rows.extend(page["data"])
        return {
            "columns": columns,
            "totalCount": total,
            "data": rows,
            "captured_at": datetime.now(UTC).isoformat(),
            "source": "TradingView ticker shares outstanding",
        }

    result["stock_shares"] = fetch_units(
        STOCK_COLUMNS,
        [
            {"left": "type", "operation": "in_range", "right": ["stock", "dr"]},
            {
                "left": "exchange",
                "operation": "in_range",
                "right": ["NASDAQ", "NYSE", "AMEX", "CBOE"],
            },
        ],
    )
    stock_units(result["stock_shares"])
    if include_etf:
        # ETF units use a different field from stock/ADR share-class shares.
        result["etf_shares"] = fetch_units(
            ETF_COLUMNS,
            [
                {"left": "type", "operation": "equal", "right": "fund"},
                {"left": "subtype", "operation": "equal", "right": "etf"},
            ],
        )
        etf_units(result["etf_shares"])
    return result
