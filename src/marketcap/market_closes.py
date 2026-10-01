"""Market-wide closing prices, independent of point-in-time share counts and ranks."""

import csv
import fcntl
import hashlib
import io
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from marketcap.calendar import NEW_YORK, latest_completed, previous_session, sessions
from marketcap.models import DataError, positive
from marketcap.providers.yahoo import YahooProvider, select_universe
from marketcap.storage import atomic_json, json_bytes

BATCH_SIZE = 20
PRICE_BASIS = "yahoo_daily_close_split_adjusted_not_dividend_adjusted"
COLUMNS = ["company_name", "ticker", "close", "trade_date", "currency", "source", "price_basis"]


def recent_closes(bundle: dict, target: date) -> dict[str, str]:
    """Use dated regular quotes only; never use today's shares to infer yesterday's cap."""
    captured = datetime.fromisoformat(bundle["captured_at"])
    close_at = sessions(target, target)[target]
    if captured.tzinfo is None or captured < close_at:
        return {}
    values = {}
    for quote in bundle["quotes"]:
        if quote.get("currency") != "USD" or quote.get("quoteType") not in {"EQUITY", "ETF"}:
            continue
        try:
            traded = datetime.fromtimestamp(quote["regularMarketTime"], UTC)
            day = traded.astimezone(NEW_YORK).date()
            if traded > captured:
                continue
            if day == target and traded <= close_at + timedelta(seconds=60):
                value = quote["regularMarketPrice"]
            elif (
                quote.get("marketState") == "REGULAR"
                and day == captured.astimezone(NEW_YORK).date()
                and previous_session(day) == target
            ):
                value = quote["regularMarketPreviousClose"]
            else:
                continue
            values[quote["symbol"]] = str(positive(value, "regular close"))
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    return values


class YahooDailyBatch:
    def __init__(self, provider: YahooProvider):
        self.provider = provider

    def fetch(self, tickers: list[str], start: date, end: date) -> dict:
        # Spark ignores period1/period2. Request a covering range and filter by
        # exchange-local dates in normalize_batch. At most 20 symbols per request.
        age = (datetime.now(UTC).date() - start).days
        history_range = next(
            (
                label
                for limit, label in ((28, "1mo"), (350, "1y"), (700, "2y"), (1700, "5y"))
                if age < limit
            ),
            "max",
        )
        response = self.provider.session.get(
            "https://query1.finance.yahoo.com/v7/finance/spark",
            params={
                "symbols": ",".join(tickers),
                "range": history_range,
                "interval": "1d",
                "includePrePost": "false",
            },
        )
        if response.status_code != 200:
            raise DataError(f"Yahoo daily batch returned HTTP {response.status_code}")
        payload = response.json().get("spark", {})
        if payload.get("error") or not isinstance(payload.get("result"), list):
            raise DataError("Yahoo daily batch is unavailable")
        return payload


def normalize_batch(payload: dict, tickers: list[str], days: list[date]) -> tuple[dict, dict]:
    valid_days = {str(day) for day in days}
    values, errors = {}, {}
    responses = {}
    for item in payload["result"]:
        ticker = item.get("symbol")
        if ticker not in tickers or ticker in responses:
            raise DataError("Unexpected or duplicate ticker in daily history response")
        responses[ticker] = item
    for ticker in tickers:
        try:
            result = responses.get(ticker, {}).get("response") or []
            if len(result) != 1:
                raise DataError("No daily history returned")
            row = result[0]
            meta = row["meta"]
            if (
                meta.get("symbol") != ticker
                or meta.get("currency") != "USD"
                or meta.get("exchangeTimezoneName") != "America/New_York"
                or meta.get("instrumentType") not in {"EQUITY", "ETF"}
                or meta.get("dataGranularity") != "1d"
            ):
                raise DataError("Expected US-listed USD daily stock or ETF prices")
            timestamps = row.get("timestamp") or []
            closes = row.get("indicators", {}).get("quote", [{}])[0].get("close") or []
            if len(timestamps) != len(closes):
                raise DataError("Daily timestamps and closes differ in length")
            prices = {}
            for timestamp, close in zip(timestamps, closes, strict=True):
                day = str(datetime.fromtimestamp(timestamp, UTC).astimezone(NEW_YORK).date())
                if day not in valid_days or close is None:
                    continue
                if day in prices:
                    raise DataError("Duplicate daily close")
                prices[day] = str(positive(close, f"{ticker} close"))
            if not prices:
                raise DataError("No completed-session prices returned")
            values[ticker] = prices
        except (DataError, KeyError, TypeError, ValueError, IndexError, OverflowError) as exc:
            errors[ticker] = str(exc)
    return values, errors


def collect_market_closes(
    provider: YahooProvider,
    *,
    start: date | None = None,
    end: date | None = None,
    now: datetime | None = None,
    bundle: dict | None = None,
    resume: bool = False,
) -> dict:
    """Default to exactly the last completed session; explicit dates opt into backfill.

    Current listing membership is the discovery set, not a claim about historical
    membership. Missing prices are recorded, never forward-filled. Historical share
    counts are not inferred from the current universe.
    """
    now = now or datetime.now(UTC)
    cutoff = latest_completed(now)
    end = end or cutoff
    start = start or end
    if end > cutoff or start > end:
        raise DataError("Request must cover completed US sessions only")
    days = list(sessions(start, end))
    root = provider.root
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".closes.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DataError("Another closing-price collector is running") from None
        report = {
            "state": "running",
            "attempted_at": now.isoformat(),
            "start_date": str(start),
            "end_date": str(end),
            "trade_dates": [str(day) for day in days],
            "requested_tickers": 0,
            "processed_tickers": 0,
            "failed_tickers": {},
            "missing_by_date": {},
            "updated_dates": [],
            "price_basis": PRICE_BASIS,
            "universe_basis": "current_listing_directory",
            "historical_market_caps_reconstructed": False,
        }
        status_path = root / "close-status.json"
        atomic_json(status_path, report)
        if not days:
            report["state"] = "unchanged"
            atomic_json(status_path, report)
            return report
        try:
            bundle = bundle if bundle is not None else provider.fetch_universe()
            _, listings, _ = select_universe(bundle, provider.settings)
            listings = {
                ticker: listing
                for ticker, listing in listings.items()
                if listing["exchange"] in provider.settings.exchanges
                and listing["security_type"] in provider.settings.security_types
            }
            tickers = sorted(listings)
            provider.captured_universe = bundle
            report["requested_tickers"] = len(tickers)
            report["universe_captured_at"] = bundle["captured_at"]
            directory = root / "close-requests" / f"{start}_{end}"
            atomic_json(directory / "universe.json", bundle)
            daily = {str(day): {} for day in days}
            quick = recent_closes(bundle, days[0]) if len(days) == 1 else {}
            for ticker, close in quick.items():
                if ticker in listings:
                    daily[str(days[0])][ticker] = {
                        "company_name": listings[ticker]["display_name"],
                        "ticker": ticker,
                        "close": close,
                        "trade_date": str(days[0]),
                        "currency": "USD",
                        "source": "yahoo",
                        "price_basis": "yahoo_regular_close",
                    }
            pending = [ticker for ticker in tickers if ticker not in quick]
            report["processed_tickers"] = len(tickers) - len(pending)
            report["prices_from_regular_quotes"] = report["processed_tickers"]
            history = YahooDailyBatch(provider)
            for offset in range(0, len(pending), BATCH_SIZE):
                batch = pending[offset : offset + BATCH_SIZE]
                key = hashlib.sha256(json_bytes(batch)).hexdigest()[:24]
                path = directory / f"{key}.json"
                if resume and path.exists():
                    payload = json.loads(path.read_text())["payload"]
                else:
                    payload = history.fetch(batch, start, end)
                    atomic_json(
                        path,
                        {
                            "tickers": batch,
                            "fetched_at": datetime.now(UTC).isoformat(),
                            "payload": payload,
                        },
                    )
                values, errors = normalize_batch(payload, batch, days)
                report["failed_tickers"].update(errors)
                for ticker, prices in values.items():
                    for day, close in prices.items():
                        daily[day][ticker] = {
                            "company_name": listings[ticker]["display_name"],
                            "ticker": ticker,
                            "close": close,
                            "trade_date": day,
                            "currency": "USD",
                            "source": "yahoo",
                            "price_basis": PRICE_BASIS,
                        }
                report["processed_tickers"] += len(batch)
                report["api_requests"] = provider.requests_made
                atomic_json(status_path, report)
                print(
                    f"Closing prices: {report['processed_tickers']}/{len(tickers)} tickers",
                    flush=True,
                )
            for day, rows in daily.items():
                missing = sorted(set(tickers) - rows.keys())
                report["missing_by_date"][day] = missing
                destination = root / "closing-prices" / f"{day}.json"
                # Preserve previously verified rows when a provider omits a ticker today.
                old = json.loads(destination.read_text()) if destination.exists() else None
                merged = {row["ticker"]: row for row in old["prices"]} if old else {}
                merged.update(rows)
                document = {
                    "trade_date": day,
                    "price_basis": "see_individual_rows",
                    "missing_tickers": sorted(set(tickers) - merged.keys()),
                    "missing_in_latest_fetch": missing,
                    "prices": [merged[ticker] for ticker in sorted(merged)],
                }
                if old != document:
                    if old:
                        revision = hashlib.sha256(json_bytes(old)).hexdigest()
                        atomic_json(
                            root / "closing-prices" / "revisions" / day / f"{revision}.json", old
                        )
                    atomic_json(destination, document)
                    report["updated_dates"].append(day)
            report["counts_by_date"] = {day: len(rows) for day, rows in daily.items()}
            report["state"] = "partial" if any(report["missing_by_date"].values()) else "ok"
            report["completed_at"] = datetime.now(UTC).isoformat()
        except Exception as exc:
            report["state"] = "error"
            report["error"] = (
                str(exc) if isinstance(exc, DataError) else "Closing-price request failed"
            )
            raise
        finally:
            report["api_requests"] = provider.requests_made
            atomic_json(status_path, report)
        return report


def export_closes(root: Path, destination: Path) -> list[str]:
    paths = sorted((root / "closing-prices").glob("????-??-??.json"))
    if not paths:
        return []
    destination.mkdir(parents=True, exist_ok=True)
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    for path in paths:
        writer.writerows(json.loads(path.read_text())["prices"])
    (destination / "close-history.csv").write_text(stream.getvalue(), encoding="utf-8")
    return [path.stem for path in paths]
