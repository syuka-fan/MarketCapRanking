"""Keyless, batched Yahoo Finance quotes with Nasdaq's public listing directories.

This source captures the latest closed session only. It cannot reconstruct historical
company capitalization or historical listing membership from today's metadata.
"""

import csv
import hashlib
import io
import json
import re
import time
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import yfinance as yf
from curl_cffi import requests

from marketcap.calendar import NEW_YORK, latest_completed, sessions
from marketcap.models import DataError, Settings, positive
from marketcap.storage import Store, atomic_json

EXCHANGES = {"NMS": "XNAS", "NGM": "XNAS", "NCM": "XNAS", "NYQ": "XNYS", "ASE": "XASE"}
METHOD = "yahoo_company_market_cap_at_regular_close_v1"


class RequestBudget:
    def __init__(self, settings: Settings):
        self.limit = settings.max_requests_per_run
        self.interval = 60 / settings.requests_per_minute
        self.calls = 0
        self.last = 0.0
        self.stop_reason = None

    def acquire(self):
        if self.stop_reason:
            raise DataError(self.stop_reason)
        if self.calls >= self.limit:
            self.stop_reason = "Public data request budget exhausted; no further requests sent"
            raise DataError(self.stop_reason)
        time.sleep(max(0, self.interval - (time.monotonic() - self.last)))
        self.last = time.monotonic()
        self.calls += 1


class BudgetSession(requests.Session):
    def __init__(self, budget: RequestBudget):
        super().__init__(impersonate="chrome")
        self.budget = budget

    def request(self, method, url, *args, **kwargs):
        self.budget.acquire()
        kwargs.setdefault("timeout", 25)
        response = super().request(method, url, *args, **kwargs)
        if response.status_code == 429:
            self.budget.stop_reason = "Yahoo rate limit reached; stopping without rapid retries"
            raise DataError(self.budget.stop_reason)
        return response


def listing_rows(text: str, nasdaq: bool) -> dict[str, dict]:
    records = {}
    for row in csv.DictReader(io.StringIO(text), delimiter="|"):
        symbol = row.get("Symbol" if nasdaq else "ACT Symbol", "")
        if not symbol or symbol.startswith("File Creation Time"):
            continue
        name = row.get("Security Name", "")
        exchange = "XNAS" if nasdaq else {"N": "XNYS", "A": "XASE"}.get(row.get("Exchange"))
        if not exchange or row.get("Test Issue") != "N" or row.get("ETF") != "N":
            continue
        # Conservative scope: explicitly named common/capital/ordinary shares only.
        if re.search(
            r"\b(preferred|depositary|depository|warrants?|units?|notes?|rights?|fund|ETN)\b",
            name,
            re.I,
        ):
            continue
        if not re.search(
            r"\b(common stock|common shares|ordinary shares|capital stock)\b", name, re.I
        ):
            continue
        yahoo_symbol = symbol.replace(".", "-")
        records[yahoo_symbol] = {"ticker": yahoo_symbol, "listing_name": name, "exchange": exchange}
    if not records:
        raise DataError("Public listing directory is empty or its schema has changed")
    return records


def issuer_name(quote: dict) -> str:
    name = (quote.get("longName") or quote.get("shortName") or "").strip()
    name = re.sub(
        r"\s+[-–]\s+(?:Class\s+\S+\s+)?(?:Common|Capital|Ordinary).*?$", "", name, flags=re.I
    )
    name = re.sub(
        r"\s+(?:Class\s+[A-Z](?:\s+(?:Common|Capital)\s+Stock)?|Common Stock)$",
        "",
        name,
        flags=re.I,
    ).strip()
    if not name:
        raise DataError("Yahoo quote has no company name")
    return name


def select_universe(bundle: dict, settings: Settings) -> tuple[dict, dict, dict]:
    listings = {
        **listing_rows(bundle["nasdaqlisted"], True),
        **listing_rows(bundle["otherlisted"], False),
    }
    quotes = {q["symbol"]: q for q in bundle["quotes"]}
    if len(quotes) != len(bundle["quotes"]):
        raise DataError("Duplicate tickers in the universe response")
    eligible = {
        ticker for ticker, listing in listings.items() if listing["exchange"] in settings.exchanges
    }
    selected = {ticker: quote for ticker, quote in quotes.items() if ticker in eligible}
    coverage = {
        "screened_tickers": len(quotes),
        "directory_eligible": len(eligible),
        "quoted_eligible": len(selected),
        "unquoted_tickers": sorted(eligible - selected.keys()),
    }
    return selected, listings, coverage


def validate_closed_quote(quote: dict, day: date, now: datetime) -> None:
    symbol = quote.get("symbol", "unknown")
    if quote.get("currency") != "USD" or quote.get("quoteType") != "EQUITY":
        raise DataError(f"{symbol}: unsupported currency or instrument type")
    if quote.get("marketState") not in {"POST", "POSTPOST", "PRE", "PREPRE", "CLOSED"}:
        raise DataError(f"{symbol}: regular session is still open; refusing intraday rankings")
    timestamp = quote.get("regularMarketTime")
    if not isinstance(timestamp, (int, float)):
        raise DataError(f"{symbol}: regular-market timestamp is missing")
    traded_at = datetime.fromtimestamp(timestamp, UTC)
    close = sessions(day, day).get(day)
    if not close or now < close or traded_at.astimezone(NEW_YORK).date() != day:
        raise DataError(f"{symbol}: regular-market quote does not match the target closing date")
    if traded_at.timestamp() > close.timestamp() + 60:
        raise DataError(f"{symbol}: regular-market timestamp is outside the closing session")
    positive(quote.get("regularMarketPrice"), f"{symbol} regular close")
    positive(quote.get("marketCap"), f"{symbol} company market cap")


class YahooProvider:
    name = "yahoo"
    latest_only = True

    def __init__(self, settings: Settings, root: Path):
        self.settings = settings
        self.root = root
        self.budget = RequestBudget(settings)
        self.session = BudgetSession(self.budget)
        self.bundle = None
        self.current_day = None
        self._quotes = {}

    @property
    def requests_made(self):
        return self.budget.calls

    def _text(self, url: str) -> str:
        self.budget.acquire()
        try:
            response = httpx.get(
                url,
                timeout=25,
                headers={
                    "User-Agent": "MarketCapRanking/0.1 https://github.com/syuka-fan/MarketCapRanking"
                },
            )
            response.raise_for_status()
        except httpx.HTTPError:
            raise DataError("Nasdaq public listing directory is unavailable") from None
        return response.text

    def screen(self, offset: int, size: int = 250) -> dict:
        query = yf.EquityQuery(
            "and",
            [
                yf.EquityQuery("eq", ["region", "us"]),
                yf.EquityQuery(
                    "is-in",
                    [
                        "exchange",
                        *[e for e, mic in EXCHANGES.items() if mic in self.settings.exchanges],
                    ],
                ),
            ],
        )
        try:
            result = yf.screen(
                query,
                offset=offset,
                size=size,
                sortField="ticker",
                sortAsc=True,
                session=self.session,
            )
        except DataError:
            raise
        except Exception:
            raise DataError("Yahoo batch request failed; retry later") from None
        if not isinstance(result, dict) or not isinstance(result.get("quotes"), list):
            raise DataError("Yahoo screener schema is unavailable")
        return result

    def fetch_bundle(self, day: str) -> dict:
        now = datetime.now(UTC)
        target = date.fromisoformat(day)
        if target != latest_completed(now):
            raise DataError("Yahoo cannot reconstruct past company caps; supply an archived bundle")
        return {"trade_date": day, **self.fetch_universe(require_closed=True)}

    def fetch_universe(self, *, require_closed: bool = False) -> dict:
        """Read every page, independent of any hand-picked history-download symbols.

        Use ticker ordering during pagination to prevent live market-cap changes
        from moving a security between pages. Rank the completed result by cap.
        """
        quotes = []
        expected = None
        while expected is None or len(quotes) < expected:
            response = self.screen(len(quotes))
            total = response.get("total")
            if not isinstance(total, int) or total <= 0:
                raise DataError("Yahoo did not report the universe size")
            if expected is not None and total != expected:
                raise DataError(
                    "Yahoo universe changed during pagination; retry after market close"
                )
            expected = total
            page = response["quotes"]
            if not page:
                raise DataError("Yahoo pagination ended before the entire universe was received")
            # Fail immediately during the session, before fetching the remaining pages.
            liquid = next((q for q in page if q.get("marketState") == "REGULAR"), None)
            if require_closed and liquid:
                raise DataError("US regular session is open; collect after close, before next open")
            quotes.extend(page)
            print(f"Yahoo universe: {len(quotes)}/{expected} tickers", flush=True)
        symbols = [q.get("symbol") for q in quotes]
        if len(symbols) != len(set(symbols)) or len(quotes) != expected:
            raise DataError("Duplicate or incomplete Yahoo pagination")
        nasdaq = self._text("https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt")
        other = self._text("https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt")
        return {
            "captured_at": datetime.now(UTC).isoformat(),
            "reported_total": expected,
            "http_requests": self.requests_made,
            "quotes": quotes,
            "nasdaqlisted": nasdaq,
            "otherlisted": other,
        }

    def _load(self, day: str):
        if self.current_day == day:
            return
        path = self.root / "bundles" / f"{day}.json"
        bundle = json.loads(path.read_text()) if path.exists() else self.fetch_bundle(day)
        if bundle.get("trade_date") != day:
            raise DataError("Archived Yahoo bundle date mismatch")
        selected, listings, self.coverage = select_universe(bundle, self.settings)
        captured = datetime.fromisoformat(bundle["captured_at"])
        excluded = []
        validated = {}
        for ticker, quote in selected.items():
            try:
                validate_closed_quote(quote, date.fromisoformat(day), captured)
                issuer_name(quote)
            except DataError as exc:
                excluded.append({"ticker": ticker, "reason": str(exc)})
            else:
                validated[ticker] = quote
        self.coverage["excluded_quotes"] = excluded
        self.coverage["rankable_tickers"] = len(validated)
        self.coverage["valid_quote_ratio"] = len(validated) / self.coverage["directory_eligible"]
        atomic_json(self.root / "coverage" / f"{day}.json", self.coverage)
        if self.coverage["valid_quote_ratio"] < self.settings.minimum_quote_coverage:
            raise DataError(
                f"Only {len(validated)}/{self.coverage['directory_eligible']} eligible tickers "
                "have validated closing quotes; refusing incomplete market coverage"
            )
        selected = validated
        if not selected:
            raise DataError("No eligible common stocks in Yahoo's listing coverage")
        # A durable capture is also the only supported source for historical recovery.
        atomic_json(path, bundle)
        self.bundle = bundle
        self._quotes = selected
        self._listings = listings
        self.current_day = day

    def tickers(self, day: str) -> list[dict]:
        self._load(day)
        return self.security_rows(self._quotes, self._listings, day)

    def security_rows(self, quotes: dict, listings: dict, day: str) -> list[dict]:
        store = Store(self.root)
        dates = [d for d in store.dates() if str(d) <= day]
        known = {s["ticker"]: s for s in store.load(dates[-1])["securities"]} if dates else {}
        names: dict[str, set[str]] = {}
        for item in known.values():
            names.setdefault(item["company_name"].casefold(), set()).add(item["company_id"])
        result = []
        for ticker, quote in quotes.items():
            name = issuer_name(quote)
            # Exact issuer-name normalization only; never fuzzy-match different businesses.
            aliases = names.get(name.casefold(), set())
            if len(aliases) > 1:
                raise DataError(f"{ticker}: issuer name is ambiguous; configure identity_overrides")
            company_id = (
                known.get(ticker, {}).get("company_id")
                or next(iter(aliases), None)
                or "issuer:" + hashlib.sha256(name.casefold().encode()).hexdigest()[:20]
            )
            result.append(
                {
                    "ticker": ticker,
                    "name": name,
                    "company_id": company_id,
                    "security_id": known.get(ticker, {}).get("security_id", f"yahoo:{ticker}"),
                    "primary_exchange": listings[ticker]["exchange"],
                    "currency_name": "usd",
                    "type": "CS",
                }
            )
        return result

    def close(self, ticker: str, day: str) -> dict:
        self._load(day)
        quote = self._quotes[ticker]
        return {
            "symbol": ticker,
            "from": day,
            "close": quote["regularMarketPrice"],
            "regular_market_time": quote["regularMarketTime"],
        }

    def details(self, ticker: str, day: str) -> dict:
        self._load(day)
        quote = self._quotes[ticker]
        return {
            "ticker": ticker,
            "market_cap_usd": quote["marketCap"],
            "market_cap_date": day,
            "market_cap_price": quote["regularMarketPrice"],
            "method": METHOD,
        }
