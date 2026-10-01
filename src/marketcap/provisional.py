"""Publish current quotes separately from immutable, completed-session history."""

import fcntl
import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from marketcap.calendar import NEW_YORK, latest_completed, regular_session_open
from marketcap.identity import identify
from marketcap.models import DataError, positive
from marketcap.providers.yahoo import (
    YahooProvider,
    coverage_by_type,
    issuer_name,
    select_universe,
    ticker_capitalization,
)
from marketcap.ranking import rank_instruments
from marketcap.storage import Store, atomic_json


def collect_provisional(provider: YahooProvider, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    root = provider.root
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DataError("Another collector is writing to this data directory") from None
        status_path = root / "status.json"
        status = json.loads(status_path.read_text()) if status_path.exists() else {}
        status.update(attempted_at=now.isoformat(), error=None, updated_dates=[])
        try:
            if not regular_session_open(now):
                raise DataError("Provisional collection requires an open regular session")
            bundle = provider.fetch_universe()
            atomic_json(root / "inspection" / "provisional-bundle.json", bundle)
            captured = datetime.fromisoformat(bundle["captured_at"])
            day = captured.astimezone(NEW_YORK).date()
            if day != now.astimezone(NEW_YORK).date():
                raise DataError("Provisional bundle date mismatch")
            selected, listings, coverage = select_universe(bundle, provider.settings)
            valid, excluded, stale = {}, [], []
            for ticker, quote in selected.items():
                try:
                    if quote.get("currency") != "USD" or quote.get("quoteType") not in {
                        "EQUITY",
                        "ETF",
                    }:
                        raise DataError("Not a USD equity or ETF")
                    timestamp = quote.get("regularMarketTime")
                    if not isinstance(timestamp, (int, float)):
                        raise DataError("Missing regular-market timestamp")
                    traded = datetime.fromtimestamp(timestamp, UTC)
                    if traded > captured or captured - traded > timedelta(days=14):
                        raise DataError("Quote timestamp is future or older than 14 days")
                    if quote.get("marketState") not in {"REGULAR", "POST", "POSTPOST", "CLOSED"}:
                        raise DataError("Unexpected market state")
                    positive(quote.get("regularMarketPrice"), "regular price")
                    ticker_capitalization(quote)
                    issuer_name(quote)
                except DataError as exc:
                    excluded.append({"ticker": ticker, "reason": str(exc)})
                else:
                    valid[ticker] = quote
                    if traded.astimezone(NEW_YORK).date() != day:
                        stale.append(ticker)
            coverage.update(
                excluded_quotes=excluded,
                rankable_tickers=len(valid),
                valid_quote_ratio=len(valid) / coverage["directory_eligible"],
                stale_quote_tickers=stale,
                by_type=coverage_by_type(listings, valid, provider.settings),
            )
            atomic_json(root / "inspection" / "provisional-coverage.json", coverage)
            if coverage["valid_quote_ratio"] < provider.settings.minimum_quote_coverage:
                raise DataError(
                    f"Provisional quotes have incomplete market coverage: "
                    f"{len(valid)}/{coverage['directory_eligible']} eligible tickers"
                )
            securities = identify(
                provider.security_rows(valid, listings, str(day)), provider.settings
            )
            rankings, prices = [], []
            for instrument_id, members in {s.security_id: [s] for s in securities}.items():
                representative = members[0]
                quote = valid[representative.ticker]
                rankings.append(
                    {
                        "instrument_id": instrument_id,
                        "company_name": representative.company_name,
                        "ticker": representative.ticker,
                        **ticker_capitalization(quote),
                        "security_type": representative.share_type,
                        "issuer_id": representative.company_id,
                    }
                )
                for security in members:
                    prices.append(
                        {
                            "instrument_id": instrument_id,
                            "company_name": representative.company_name,
                            "security_id": security.security_id,
                            "ticker": security.ticker,
                            "close": str(valid[security.ticker]["regularMarketPrice"]),
                            "quote_date": datetime.fromtimestamp(
                                valid[security.ticker]["regularMarketTime"], UTC
                            )
                            .astimezone(NEW_YORK)
                            .date()
                            .isoformat(),
                            "currency": "USD",
                        }
                    )
            store = Store(root)
            dates = store.dates()
            previous = store.load(dates[-1]) if dates else None
            if previous and (
                previous["source"] != provider.name
                or previous["policy"] != provider.settings.policy()
            ):
                raise DataError("Provider or universe policy differs from stored history")
            if previous and len(rankings) < (
                len(previous["rankings"]) * provider.settings.minimum_universe_ratio
            ):
                raise DataError("Provisional universe shrank unexpectedly")
            snapshot = {
                "schema_version": 2,
                "trade_date": str(day),
                "collected_at": captured.isoformat(),
                "source": "yahoo",
                "is_demo": False,
                "is_final_close": False,
                "policy": provider.settings.policy(),
                "coverage": coverage,
                "securities": [asdict(s) for s in securities],
                "rankings": rank_instruments(rankings),
                "prices": prices,
            }
            # Never write provisional quotes under snapshots/ or closing bundles/.
            atomic_json(root / "provisional-bundle.json", bundle)
            atomic_json(root / "provisional.json", snapshot)
            status.update(
                state="provisional",
                expected_trade_date=str(latest_completed(now)),
                latest_trade_date=str(dates[-1]) if dates else None,
                last_success_at=previous["collected_at"] if previous else None,
                provisional_at=captured.isoformat(),
                instrument_count=len(rankings),
                ticker_count=len(prices),
                coverage=coverage,
            )
        except Exception as exc:
            status.update(state="error", error=str(exc))
            raise
        finally:
            status["api_requests"] = provider.requests_made
            atomic_json(status_path, status)
        return status
