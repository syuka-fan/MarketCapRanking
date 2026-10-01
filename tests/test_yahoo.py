import json
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from marketcap.models import DataError
from marketcap.pipeline import run
from marketcap.providers.yahoo import (
    BudgetSession,
    RequestBudget,
    YahooProvider,
    listing_rows,
    validate_closed_quote,
)
from marketcap.storage import Store

NASDAQ = (
    (
        "Symbol|Security Name|Market Category|Test Issue|Financial Status|"
        "Round Lot Size|ETF|NextShares\n"
    )
    + """ALPHA|Alpha Inc. - Class A Common Stock|Q|N|N|100|N|N
ALPHB|Alpha Inc. - Class B Common Stock|Q|N|N|100|N|N
ETF|Example ETF|Q|N|N|100|Y|N
ADR|Example American Depositary Shares|Q|N|N|100|N|N
File Creation Time: 0930202622:00|||||||
"""
)
OTHER = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
BETA|Beta Inc. Common Stock|N|BETA|N|100|N|BETA
File Creation Time: 0930202622:00|||||||
"""


def quote(symbol="ALPHA", **changes):
    return {
        "symbol": symbol,
        "longName": "Alpha Inc." if symbol != "BETA" else "Beta Inc.",
        "marketState": "POSTPOST",
        "regularMarketTime": 1790798400,
        "regularMarketPrice": 10,
        "marketCap": 1000,
        "currency": "USD",
        "quoteType": "EQUITY",
        **changes,
    }


def bundle():
    return {
        "trade_date": "2026-09-30",
        "captured_at": "2026-10-01T00:00:00+00:00",
        "nasdaqlisted": NASDAQ,
        "otherlisted": OTHER,
        "quotes": [
            quote(),
            quote("ALPHB", regularMarketPrice=9, marketCap=950),
            quote("BETA", marketCap=2000),
        ],
    }


def test_directories_exclude_etf_adr_and_map_class_symbols():
    assert set(listing_rows(NASDAQ, True)) == {"ALPHA", "ALPHB"}
    assert listing_rows(OTHER.replace("BETA", "BRK.B"), False)["BRK-B"]["exchange"] == "XNYS"


def test_only_closed_date_matched_regular_quotes_are_accepted():
    day = date(2026, 9, 30)
    now = datetime(2026, 10, 1, tzinfo=UTC)
    validate_closed_quote(quote(), day, now)
    with pytest.raises(DataError, match="still open"):
        validate_closed_quote(quote(marketState="REGULAR"), day, now)
    with pytest.raises(DataError, match="closing date"):
        validate_closed_quote(quote(regularMarketTime=1790712000), day, now)
    with pytest.raises(DataError, match="market cap"):
        validate_closed_quote(quote(marketCap=None), day, now)


def test_bulk_company_cap_is_not_summed_and_can_be_recovered_without_network(
    tmp_path, settings, now, monkeypatch
):
    settings = replace(settings, canonical_tickers={"Alpha Inc.": "ALPHA"})
    provider = YahooProvider(settings, tmp_path)
    monkeypatch.setattr(provider, "fetch_bundle", lambda day: bundle())
    run(provider, settings, tmp_path, now=now)
    snapshot = Store(tmp_path).load(date(2026, 9, 30))
    assert len(snapshot["prices"]) == 3
    assert len(snapshot["rankings"]) == 2
    alpha = next(r for r in snapshot["rankings"] if r["company_name"] == "Alpha Inc.")
    assert alpha["market_cap_usd"] == "1000.00"
    assert snapshot["coverage"]["quoted_eligible"] == 3
    again = YahooProvider(settings, tmp_path)
    monkeypatch.setattr(again, "fetch_bundle", lambda day: pytest.fail("Must reuse the archive"))
    run(again, settings, tmp_path, now=now, refresh=True)


def test_no_fabricated_historical_caps(tmp_path, settings, now, monkeypatch):
    provider = YahooProvider(settings, tmp_path)
    monkeypatch.setattr(
        provider, "fetch_bundle", lambda day: pytest.fail("No historical network call")
    )
    status = run(
        provider, settings, tmp_path, now=now, start=date(2026, 9, 29), end=date(2026, 9, 29)
    )
    assert status["state"] == "incomplete"
    assert status["unrecoverable_dates"] == ["2026-09-29"]
    assert Store(tmp_path).dates() == []


def test_request_budget_counts_every_attempt_and_paces_calls(settings, monkeypatch):
    elapsed = [0.0]
    waits = []
    monkeypatch.setattr("marketcap.providers.yahoo.time.monotonic", lambda: elapsed[0])

    def sleep(duration):
        waits.append(duration)
        elapsed[0] += duration

    monkeypatch.setattr("marketcap.providers.yahoo.time.sleep", sleep)
    budget = RequestBudget(replace(settings, requests_per_minute=4, max_requests_per_run=2))
    budget.acquire()
    budget.acquire()
    with pytest.raises(DataError, match="budget"):
        budget.acquire()
    assert budget.calls == 2
    assert waits[-1] == 15


def test_live_collection_stops_after_first_page_during_regular_session(
    tmp_path, settings, now, monkeypatch
):
    from marketcap.providers import yahoo

    provider = YahooProvider(settings, tmp_path)
    calls = []
    monkeypatch.setattr(yahoo, "latest_completed", lambda now: date(2026, 9, 30))

    def screen(offset):
        calls.append(offset)
        return {"total": 1000, "quotes": [quote(marketState="REGULAR")]}

    monkeypatch.setattr(provider, "screen", screen)
    with pytest.raises(DataError, match="session is open"):
        provider.fetch_bundle("2026-09-30")
    assert calls == [0]


def test_stale_date_archive_is_rejected(tmp_path, settings):
    (tmp_path / "bundles").mkdir()
    invalid = bundle()
    invalid["trade_date"] = "2026-09-29"
    (tmp_path / "bundles/2026-09-30.json").write_text(json.dumps(invalid))
    with pytest.raises(DataError, match="date mismatch"):
        YahooProvider(settings, tmp_path).tickers("2026-09-30")


def test_429_stops_later_requests_at_the_session_boundary(settings, monkeypatch):
    from types import SimpleNamespace

    from curl_cffi import requests

    sent = []

    def rate_limited(*args, **kwargs):
        sent.append(1)
        return SimpleNamespace(status_code=429)

    monkeypatch.setattr(requests.Session, "request", rate_limited)
    monkeypatch.setattr("marketcap.providers.yahoo.time.sleep", lambda seconds: None)
    session = BudgetSession(RequestBudget(settings))
    for _ in range(2):
        with pytest.raises(DataError, match="rate limit"):
            session.get("https://query1.finance.yahoo.com/example")
    assert len(sent) == 1
    assert session.budget.calls == 1


def large_bundle():
    quotes = [
        quote(f"S{i:04}", longName=f"Company {i} Inc.", marketCap=(i + 1) * 10000)
        for i in range(300)
    ] + [quote(), quote("ALPHB"), quote("BETA")]
    header = NASDAQ.splitlines()[0]
    listing = (
        header
        + "\n"
        + "\n".join(
            f"{q['symbol']}|{q['longName']} - Common Stock|Q|N|N|100|N|N"
            for q in quotes
            if q["symbol"] != "BETA"
        )
    )
    return {**bundle(), "quotes": quotes, "nasdaqlisted": listing}


def test_all_pages_become_rankings_with_no_fixed_ticker_or_top_n_limit(
    tmp_path, settings, now, monkeypatch
):
    data = large_bundle()
    settings = replace(settings, minimum_companies=300)
    provider = YahooProvider(settings, tmp_path)
    offsets = []

    def screen(offset):
        offsets.append(offset)
        return {"total": len(data["quotes"]), "quotes": data["quotes"][offset : offset + 250]}

    monkeypatch.setattr(provider, "screen", screen)
    monkeypatch.setattr(
        provider,
        "_text",
        lambda url: data["nasdaqlisted" if url.endswith("/nasdaqlisted.txt") else "otherlisted"],
    )
    captured = provider.fetch_universe(require_closed=True)
    monkeypatch.setattr(provider, "fetch_bundle", lambda day: {**captured, "trade_date": day})
    status = run(provider, settings, tmp_path, now=now)
    assert offsets == [0, 250]
    assert status["ticker_count"] == 303
    assert status["company_count"] == 302
    snapshot = Store(tmp_path).load(date(2026, 9, 30))
    assert snapshot["rankings"][0]["canonical_ticker"] == "S0299"
    assert {row["ticker"] for row in snapshot["prices"]} == {q["symbol"] for q in data["quotes"]}


def test_small_missing_cap_is_reported_but_mass_missing_data_is_rejected(
    tmp_path, settings, now, monkeypatch
):
    data = large_bundle()
    data["quotes"][0]["marketCap"] = None
    provider = YahooProvider(settings, tmp_path)
    monkeypatch.setattr(provider, "fetch_bundle", lambda day: data)
    run(provider, settings, tmp_path, now=now)
    snapshot = Store(tmp_path).load(date(2026, 9, 30))
    assert len(snapshot["prices"]) == 302
    assert snapshot["coverage"]["excluded_quotes"][0]["ticker"] == "S0000"
    assert snapshot["coverage"]["valid_quote_ratio"] >= 0.98
    for q in data["quotes"][:10]:
        q["marketCap"] = None
    other = tmp_path / "failed"
    broken = YahooProvider(settings, other)
    monkeypatch.setattr(broken, "fetch_bundle", lambda day: data)
    with pytest.raises(DataError, match="incomplete market coverage"):
        run(broken, settings, other, now=now)
    assert Store(other).dates() == []
    assert (
        len(json.loads((other / "coverage/2026-09-30.json").read_text())["excluded_quotes"]) == 10
    )


def test_intraday_universe_inspection_never_creates_a_daily_snapshot(tmp_path, settings):
    from marketcap.inspection import inspect_universe

    data = large_bundle()
    for q in data["quotes"]:
        q["marketState"] = "REGULAR"
    report = inspect_universe(YahooProvider(settings, tmp_path), data)
    assert report["company_count"] == 302
    assert report["rankable_tickers"] == 303
    assert report["is_final_close"] is False
    assert report["market_states"] == {"REGULAR": 303}
    assert report["top_10"][0]["ticker"] == "S0299"
    assert (tmp_path / "inspection/rankings-preview.csv").exists()
    assert Store(tmp_path).dates() == []


def test_duplicate_pagination_does_not_publish_an_incomplete_universe(
    tmp_path, settings, monkeypatch
):
    provider = YahooProvider(settings, tmp_path)
    monkeypatch.setattr(provider, "screen", lambda offset: {"total": 2, "quotes": [quote()]})
    with pytest.raises(DataError, match="Duplicate or incomplete"):
        provider.fetch_universe(require_closed=True)
