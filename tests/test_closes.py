import json
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from marketcap.closes import COLUMNS, download_closes, normalize, read_symbols
from marketcap.models import DataError

START = date(2026, 9, 28)
NOW = datetime(2026, 10, 1, 15, tzinfo=UTC)  # Oct 1 regular session is still open.


def history(days=("2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01"), close=10):
    return pd.DataFrame(
        {
            "Open": close,
            "High": close + 1,
            "Low": close - 1,
            "Close": close,
            "Volume": 1000,
            "Stock Splits": 0,
        },
        index=pd.DatetimeIndex(days, tz="America/New_York"),
    )


class HistoryProvider:
    def __init__(self):
        self.budget = SimpleNamespace(calls=0, stop_reason=None)
        self.calls = []
        self.frame = history()
        self.failed = set()

    def fetch(self, ticker, start, end):
        self.calls.append((ticker, start, end))
        self.budget.calls += 1
        if ticker in self.failed:
            raise DataError("No history returned")
        return self.frame.copy()


def test_only_completed_sessions_and_company_ticker_price_column_order(tmp_path):
    provider = HistoryProvider()
    result = download_closes(
        provider, {"GOOG": "Alphabet", "GOOGL": "Alphabet"}, tmp_path, start=START, now=NOW
    )
    assert result["state"] == "ok"
    assert result["completed_through"] == "2026-09-30"
    for ticker in ("GOOG", "GOOGL"):
        data = pd.read_csv(tmp_path / "us_daily" / f"{ticker}.csv")
        assert list(data.columns) == COLUMNS
        assert data.trade_date.tolist() == ["2026-09-28", "2026-09-29", "2026-09-30"]
        assert data.close.tolist() == [10, 10, 10]


def test_incremental_overlap_idempotency_and_recover_corrupt_state(tmp_path):
    provider = HistoryProvider()
    download_closes(provider, {"AAPL": "Apple"}, tmp_path, start=START, now=NOW)
    path = tmp_path / "us_daily/AAPL.csv"
    original_time = path.stat().st_mtime_ns
    (tmp_path / "download_state.json").write_text("{broken")
    result = download_closes(provider, {"AAPL": "Apple"}, tmp_path, now=NOW)
    assert result["unchanged"] == ["AAPL"]
    assert provider.calls[-1][1] == date(2026, 9, 23)
    assert path.stat().st_mtime_ns == original_time
    assert json.loads((tmp_path / "download_state.json").read_text())["AAPL"]["rows"] == 3


def test_corrected_same_row_count_and_split_basis_refetches_older_history(tmp_path):
    provider = HistoryProvider()
    provider.frame = history(("2026-09-01", "2026-09-28", "2026-09-30"))
    download_closes(provider, {"AAPL": "Apple"}, tmp_path, start=date(2026, 9, 1), now=NOW)
    provider.frame = history(("2026-09-01", "2026-09-28", "2026-09-30"), close=5)
    result = download_closes(provider, {"AAPL": "Apple"}, tmp_path, now=NOW)
    assert result["updated"] == ["AAPL"]
    assert provider.calls[-1][1] == date(2026, 9, 1)
    assert pd.read_csv(tmp_path / "us_daily/AAPL.csv").close.tolist() == [5, 5, 5]


def test_partial_failure_preserves_previous_csv_and_state(tmp_path):
    provider = HistoryProvider()
    symbols = {"AAPL": "Apple", "MSFT": "Microsoft"}
    download_closes(provider, symbols, tmp_path, start=START, now=NOW)
    previous = (tmp_path / "us_daily/AAPL.csv").read_bytes()
    state = json.loads((tmp_path / "download_state.json").read_text())["AAPL"]
    provider.failed.add("AAPL")
    result = download_closes(provider, symbols, tmp_path, now=NOW)
    assert result["state"] == "incomplete"
    assert result["failed"] == {"AAPL": "No history returned"}
    assert result["unchanged"] == ["MSFT"]
    assert (tmp_path / "us_daily/AAPL.csv").read_bytes() == previous
    assert json.loads((tmp_path / "download_state.json").read_text())["AAPL"] == state


def test_budget_exhaustion_skips_remaining_tickers(tmp_path):
    provider = HistoryProvider()

    def limited(*args):
        provider.budget.stop_reason = "Budget exhausted"
        raise DataError("Budget exhausted")

    provider.fetch = limited
    report = download_closes(
        provider, {"AAPL": "Apple", "MSFT": "Microsoft"}, tmp_path, start=START, now=NOW
    )
    assert report["state"] == "incomplete"
    assert report["skipped"] == ["MSFT"]
    assert not (tmp_path / "download_state.json").exists()


def test_early_close_holiday_multiindex_and_no_adjusted_close_substitution():
    # July 2, 2026 closes at 13:00 ET; July 3 is the observed holiday.
    frame = history(("2026-07-02", "2026-07-03"))
    frame["Adj Close"] = 9
    frame.columns = pd.MultiIndex.from_product([frame.columns, ["AAPL"]])
    clean = normalize(frame, "AAPL", "Apple", date(2026, 7, 2), date(2026, 7, 3))
    assert clean.trade_date.tolist() == ["2026-07-02"]
    assert clean.close.tolist() == [10]


def test_symbols_match_reference_format_and_reject_unsafe_paths(tmp_path):
    path = tmp_path / "symbols.json"
    path.write_text(json.dumps({"us": {"AAPL": "Apple", "BRK-B": "Berkshire"}, "kr": {}}))
    assert read_symbols(path, "brk-b,BRK-B") == {"BRK-B": "Berkshire"}
    with pytest.raises(DataError, match="Add these tickers"):
        read_symbols(path, "MISSING")
    path.write_text(json.dumps({"us": {"../secret": "invalid"}}))
    with pytest.raises(DataError, match="US Yahoo tickers"):
        read_symbols(path)


def test_incomplete_split_refetch_preserves_previous_adjustment_basis(tmp_path):
    provider = HistoryProvider()
    provider.frame = history(("2026-09-01", "2026-09-28", "2026-09-30"))
    download_closes(provider, {"AAPL": "Apple"}, tmp_path, start=date(2026, 9, 1), now=NOW)
    previous = (tmp_path / "us_daily/AAPL.csv").read_bytes()
    provider.frame = history(("2026-09-28", "2026-09-30"), close=5)
    result = download_closes(provider, {"AAPL": "Apple"}, tmp_path, now=NOW)
    assert result["state"] == "incomplete"
    assert "revised history is incomplete" in result["failed"]["AAPL"]
    assert (tmp_path / "us_daily/AAPL.csv").read_bytes() == previous
