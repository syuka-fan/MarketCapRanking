from dataclasses import replace
from datetime import UTC, datetime

import pytest

from marketcap.models import Settings


class SampleProvider:
    name = "sample"

    def __init__(self):
        self.calls = []
        self.bad_date = False
        self.bad_shares = False
        self.price_offset = 0
        self.omit_beta = False
        self.renamed = False

    def tickers(self, day):
        self.calls.append(("tickers", day))
        data = [
            {"ticker": "ALPHA.A", "name": "Alpha Inc.", "cik": "1", "share_class_figi": "A1"},
            {"ticker": "ALPHA.B", "name": "Alpha Inc.", "cik": "1", "share_class_figi": "A2"},
            {"ticker": "BETA", "name": "Beta Inc.", "cik": "2", "share_class_figi": "B1"},
        ]
        if self.omit_beta:
            data = data[:2]
        if self.renamed:
            data[0]["ticker"] = "RENAMED.A"
        return [
            {**r, "primary_exchange": "XNAS", "type": "CS", "currency_name": "usd"} for r in data
        ]

    def close(self, ticker, day):
        self.calls.append(("close", ticker, day))
        price = {"ALPHA.A": 10, "RENAMED.A": 10, "ALPHA.B": 9, "BETA": 20}[ticker]
        return {
            "symbol": ticker,
            "from": "2000-01-01" if self.bad_date else day,
            "close": price + self.price_offset,
            "afterHours": 9999,
        }

    def details(self, ticker, day):
        self.calls.append(("details", ticker, day))
        return {
            "ticker": ticker,
            "cik": "2" if ticker == "BETA" else "1",
            "weighted_shares_outstanding": None if self.bad_shares else 100,
        }


@pytest.fixture
def settings():
    return replace(
        Settings(), minimum_instruments=1, minimum_universe_ratio=0.9, security_types=("CS",)
    )


@pytest.fixture
def provider():
    return SampleProvider()


@pytest.fixture
def now():
    return datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
