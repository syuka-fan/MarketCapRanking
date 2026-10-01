import math
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from marketcap.models import Settings
from marketcap.pipeline import run

NAMES = [
    "Northstar",
    "Meridian",
    "Juniper",
    "Atlas",
    "Cobalt",
    "Evergreen",
    "Solstice",
    "Orion",
    "Cedar",
    "Aurora",
    "Summit",
    "Lumen",
    "Harbor",
    "Maple",
    "Vela",
    "Ember",
    "Willow",
    "Terra",
    "Nova",
    "Aspen",
    "River",
    "Echo",
    "Cove",
    "Sage",
]


class DemoProvider:
    """Deterministic fictional companies. Never used as a live-data fallback."""

    name = "demo"

    def tickers(self, day: str) -> list[dict]:
        result = []
        for index, name in enumerate(NAMES):
            for suffix in ["A", "B"] if index in (0, 3) else ["A"]:
                result.append(
                    {
                        "ticker": f"D{index:02}{suffix}",
                        "name": f"{name} (가상)",
                        "cik": str(index + 1),
                        "share_class_figi": f"DEMO{index:02}{suffix}",
                        "primary_exchange": "XNAS",
                        "type": "CS",
                        "currency_name": "usd",
                    }
                )
        return result

    def close(self, ticker: str, day: str) -> dict:
        index = int(ticker[1:3])
        t = (date.fromisoformat(day) - date(2025, 1, 1)).days
        price = 290 - index * 7 + 26 * math.sin(t / 17 + index / 2) + 14 * math.cos(t / 37 + index)
        return {
            "symbol": ticker,
            "from": day,
            "close": round(price, 2),
            "afterHours": round(price * 1.1, 2),
        }

    def details(self, ticker: str, day: str) -> dict:
        return {
            "ticker": ticker,
            "cik": str(int(ticker[1:3]) + 1),
            "weighted_shares_outstanding": 10_000_000_000,
        }


def generate(root: Path) -> None:
    settings = replace(Settings(), minimum_instruments=1, minimum_universe_ratio=0.1)
    now = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    run(
        DemoProvider(),
        settings,
        root,
        now=now,
        start=date(2025, 10, 1),
        end=now.date() - timedelta(days=1),
    )
