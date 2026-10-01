import csv
import json
from datetime import UTC, date, datetime

import pytest
from test_yahoo import bundle, quote

from marketcap.calendar import sessions
from marketcap.export import export_site
from marketcap.market_closes import (
    YahooDailyBatch,
    collect_market_closes,
    normalize_batch,
    recent_closes,
)
from marketcap.models import DataError
from marketcap.pipeline import run
from marketcap.providers.yahoo import YahooProvider
from marketcap.storage import Store


def history(tickers, days, close=10):
    return {
        "result": [
            {
                "symbol": ticker,
                "response": [
                    {
                        "meta": {
                            "symbol": ticker,
                            "currency": "USD",
                            "exchangeTimezoneName": "America/New_York",
                            "instrumentType": "EQUITY",
                            "dataGranularity": "1d",
                        },
                        "timestamp": [
                            int(datetime.combine(day, datetime.min.time(), UTC).timestamp())
                            + 15 * 3600
                            for day in days
                        ],
                        "indicators": {"quote": [{"close": [close] * len(days)}]},
                    }
                ],
            }
            for ticker in tickers
        ]
    }


def test_history_excludes_unfinished_sessions_and_never_fills_missing_prices():
    days = [date(2026, 9, 29), date(2026, 9, 30), date(2026, 10, 1)]
    payload = history(["AAPL"], days)
    payload["result"][0]["response"][0]["indicators"]["quote"][0]["close"][0] = None
    values, errors = normalize_batch(payload, ["AAPL", "MISSING"], days[:2])
    assert values == {"AAPL": {"2026-09-30": "10"}}
    assert errors == {"MISSING": "No daily history returned"}


def test_dated_previous_close_ignores_intraday_afterhours_and_missing_shares():
    data = bundle()
    data["captured_at"] = "2026-10-01T15:00:00+00:00"
    data["quotes"] = [
        quote(
            marketState="REGULAR",
            regularMarketTime=1790865000,
            regularMarketPrice=999,
            postMarketPrice=888,
            regularMarketPreviousClose=12,
            sharesOutstanding=None,
        )
    ]
    assert recent_closes(data, date(2026, 9, 30)) == {"ALPHA": "12"}
    data["quotes"][0]["regularMarketTime"] = 1790629200  # Older session, not September 30.
    assert recent_closes(data, date(2026, 9, 30)) == {}
    data["captured_at"] = "2026-09-30T15:00:00+00:00"
    assert recent_closes(data, date(2026, 9, 30)) == {}


def test_backfill_all_directory_tickers_without_fabricating_caps(
    tmp_path, settings, now, monkeypatch
):
    provider = YahooProvider(settings, tmp_path)
    data = bundle()
    data["quotes"] = []  # Prices must include directory members with no current cap/quote.
    days = list(sessions(date(2026, 9, 17), date(2026, 9, 30)))
    calls = []

    def fetch(self, tickers, start, end):
        calls.append((tickers, start, end))
        return history(tickers, days + [date(2026, 10, 1)])

    monkeypatch.setattr(YahooDailyBatch, "fetch", fetch)
    report = collect_market_closes(provider, start=days[0], now=now, bundle=data)
    assert len(report["trade_dates"]) == 10
    assert set(calls[0][0]) == {"ALPHA", "ALPHB", "BETA"}
    assert report["counts_by_date"] == {str(day): 3 for day in days}
    assert Store(tmp_path).dates() == []
    assert not (tmp_path / "closing-prices/2026-10-01.json").exists()
    export_site(tmp_path, tmp_path / "site")
    index = json.loads((tmp_path / "site/index.json").read_text())
    assert index["closed_dates"] == index["axis_dates"] == []
    assert index["price_dates"] == [str(day) for day in days]
    with (tmp_path / "site/close-history.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 30
    assert set(rows[0]) >= {"company_name", "ticker", "close", "trade_date"}


def test_daily_rereads_only_last_session_and_preserves_old_dates(
    tmp_path, settings, now, monkeypatch
):
    provider = YahooProvider(settings, tmp_path)
    data = bundle()
    data["quotes"] = []
    value = [10]
    calls = []

    def fetch(self, tickers, start, end):
        calls.append((start, end))
        return history(tickers, list(sessions(start, end)), close=value[0])

    monkeypatch.setattr(YahooDailyBatch, "fetch", fetch)
    collect_market_closes(provider, start=date(2026, 9, 29), now=now, bundle=data)
    older = (tmp_path / "closing-prices/2026-09-29.json").read_bytes()
    value[0] = 12
    collect_market_closes(provider, now=now, bundle=data)
    assert calls[-1] == (date(2026, 9, 30), date(2026, 9, 30))
    assert (tmp_path / "closing-prices/2026-09-29.json").read_bytes() == older
    assert (
        json.loads((tmp_path / "closing-prices/2026-09-30.json").read_text())["prices"][0]["close"]
        == "12"
    )
    assert len(list((tmp_path / "closing-prices/revisions/2026-09-30").glob("*.json"))) == 1
    calls_before = len(calls)
    collect_market_closes(provider, now=now, bundle=data)
    assert len(calls) == calls_before + 1  # No network skip for an already saved date.


def test_daily_closed_quote_fast_path_requires_no_history_or_shares(
    tmp_path, settings, now, monkeypatch
):
    provider = YahooProvider(settings, tmp_path)
    data = bundle()
    for row in data["quotes"]:
        row["sharesOutstanding"] = None
    monkeypatch.setattr(YahooDailyBatch, "fetch", lambda *args: pytest.fail("Unneeded history"))
    report = collect_market_closes(provider, bundle=data, now=now)
    assert report["prices_from_regular_quotes"] == 3
    assert report["counts_by_date"] == {"2026-09-30": 3}


def test_failure_keeps_prices_and_explicit_resume_reuses_saved_batches(
    tmp_path, settings, now, monkeypatch
):
    provider = YahooProvider(settings, tmp_path)
    data = bundle()
    data["quotes"] = []
    monkeypatch.setattr(YahooDailyBatch, "fetch", lambda self, ts, start, end: history(ts, [end]))
    collect_market_closes(provider, start=date(2026, 9, 29), now=now, bundle=data)
    path = tmp_path / "closing-prices/2026-09-30.json"
    before = path.read_bytes()

    def fail(*args):
        raise DataError("Rate limit")

    monkeypatch.setattr(YahooDailyBatch, "fetch", fail)
    with pytest.raises(DataError, match="Rate limit"):
        collect_market_closes(provider, now=now, bundle=data)
    assert path.read_bytes() == before
    report = collect_market_closes(
        provider, start=date(2026, 9, 29), now=now, bundle=data, resume=True
    )
    assert report["state"] == "partial"  # September 29 is absent, never forward-filled.
    assert report["missing_by_date"]["2026-09-29"] == ["ALPHA", "ALPHB", "BETA"]


def test_daily_rank_refresh_fetches_live_even_when_archive_exists(
    tmp_path, settings, now, monkeypatch
):
    provider = YahooProvider(settings, tmp_path)
    monkeypatch.setattr(provider, "fetch_bundle", lambda day: bundle())
    run(provider, settings, tmp_path, now=now)
    data = bundle()
    data["quotes"][0]["regularMarketPrice"] = 11
    fresh = YahooProvider(settings, tmp_path)
    monkeypatch.setattr(fresh, "fetch_bundle", lambda day: data)
    run(fresh, settings, tmp_path, now=now)
    row = next(
        row for row in Store(tmp_path).load(date(2026, 9, 30))["prices"] if row["ticker"] == "ALPHA"
    )
    assert row["close"] == "11"
    assert len(list((tmp_path / "snapshots/2026-09-30/revisions").iterdir())) == 2


def test_future_request_rejected_before_network(tmp_path, settings, now, monkeypatch):
    provider = YahooProvider(settings, tmp_path)
    monkeypatch.setattr(provider, "fetch_universe", lambda: pytest.fail("Future query"))
    with pytest.raises(DataError, match="completed"):
        collect_market_closes(provider, end=date(2026, 10, 1), now=now)


@pytest.mark.parametrize("provisional", [True, False])
def test_cli_intraday_always_saves_previous_close_before_optional_live_quotes(
    tmp_path, settings, monkeypatch, provisional
):
    import sys
    from dataclasses import asdict

    from marketcap import cli, market_closes, pipeline
    from marketcap import provisional as provisional_module

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 1, 15, tzinfo=UTC)

    for module in (cli, market_closes, pipeline, provisional_module):
        monkeypatch.setattr(module, "datetime", Clock)
    data = bundle()
    data["captured_at"] = "2026-10-01T15:00:00+00:00"
    for row in data["quotes"]:
        row.update(
            marketState="REGULAR",
            regularMarketTime=1790865000,
            regularMarketPreviousClose=10,
            regularMarketPrice=11,
        )
    calls = []

    def fetch(self):
        calls.append(1)
        return data

    monkeypatch.setattr(YahooProvider, "fetch_universe", fetch)
    monkeypatch.setattr(YahooDailyBatch, "fetch", lambda *args: pytest.fail("Unexpected history"))
    configuration = tmp_path / "settings.json"
    configuration.write_text(json.dumps(asdict(settings)))
    argv = ["marketcap", "collect", "--data-dir", str(tmp_path), "--settings", str(configuration)]
    if provisional:
        argv.append("--allow-provisional")
    monkeypatch.setattr(sys, "argv", argv)
    assert cli.main() == 0
    prices = json.loads((tmp_path / "closing-prices/2026-09-30.json").read_text())["prices"]
    assert len(prices) == 3
    assert {row["close"] for row in prices} == {"10"}
    assert Store(tmp_path).dates() == []  # Current shares never enter historical caps.
    assert calls == [1]  # The current capture is shared, not fetched a second time.
    if provisional:
        live = json.loads((tmp_path / "provisional.json").read_text())
        assert live["trade_date"] == "2026-10-01"
        assert {row["close"] for row in live["prices"]} == {"11"}
    else:
        assert not (tmp_path / "provisional.json").exists()
    assert json.loads((tmp_path / "status.json").read_text())["closing_prices"]["state"] == "ok"
