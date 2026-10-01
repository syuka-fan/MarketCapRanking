"""Check exported or deployed data, including the separation of provisional quotes."""

import argparse
import csv
import hashlib
import io
import json
import math
import time
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from urllib.request import Request, urlopen


def verify(location: str, publication_id: str | None = None) -> dict:
    def read(filename):
        if location.startswith(("http://", "https://")):
            request = Request(
                f"{location.rstrip('/')}/{filename}?check={time.time_ns()}",
                headers={"Cache-Control": "no-cache", "User-Agent": "MarketCapRanking-check"},
            )
            with urlopen(request, timeout=30) as response:
                return response.read().decode()
        return (Path(location) / filename).read_bytes().decode()

    index = json.loads(read("index.json"))
    assert index["schema_version"] == 2, "Unsupported schema"
    if publication_id:
        assert index.get("publication_id") == publication_id, "Old deployment is still served"
    dates = index["dates"]
    assert dates == sorted(set(dates)), "Duplicate or unordered dates"
    assert dates, "No ranking data was published"
    closed = index.get("closed_dates", dates)
    provisional = index.get("provisional_date")
    assert provisional not in closed, "Provisional date entered closing history"
    assert provisional not in index["axis_dates"], "Provisional date entered chart history"
    latest = json.loads(read(f"days/{dates[-1]}.json"))
    rows = latest["rows"]
    assert rows, "Ranking table is empty"
    assert latest.get("is_final_close", True) == (provisional is None)
    seen_companies, seen_tickers = set(), set()
    previous_cap, expected_rank = math.inf, 0
    for position, row in enumerate(rows, 1):
        amount = row["market_cap_usd"]
        assert math.isfinite(amount) and 0 < amount <= previous_cap, "Invalid cap ordering"
        if amount != previous_cap:
            expected_rank = position
        assert row["rank"] == expected_rank, "Incorrect competition rank"
        previous_cap = amount
        assert row["instrument_id"] not in seen_companies, "Duplicate company"
        seen_companies.add(row["instrument_id"])
        assert len(row["prices"]) == 1, "A rank must contain exactly one ticker"
        assert row["prices"][0]["ticker"] == row["ticker"], "Rank/price ticker mismatch"
        calculated = (
            Decimal(str(row["prices"][0]["close"])) * Decimal(row["shares_outstanding"])
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        assert abs(calculated - Decimal(str(amount))) <= Decimal("0.01"), (
            "Ticker cap does not equal price times ticker shares"
        )
        for price in row["prices"]:
            assert math.isfinite(price["close"]) and price["close"] > 0, "Invalid price"
            assert price["ticker"] not in seen_tickers, "Duplicate ticker"
            seen_tickers.add(price["ticker"])
            if provisional:
                assert price.get("quote_date", "") <= provisional, "Future quote date"
    for company in index["instruments"][:10]:
        history = json.loads(read(f"instruments/{company['history_file']}"))
        assert set(history) <= set(closed), "Non-closing point found in company history"
    rankings = list(csv.DictReader(io.StringIO(read("latest-rankings.csv"))))
    prices = list(csv.DictReader(io.StringIO(read("latest-prices.csv"))))
    assert len(rankings) == len(rows), "CSV company count differs from the table"
    assert {p["ticker"] for p in prices} == seen_tickers, "CSV ticker coverage differs"
    assert [r["ticker"] for r in rankings] == [r["ticker"] for r in rows]
    if provisional:
        assert all(r["is_final_close"] == "False" for r in rankings + prices)
        assert "price" in prices[0] and "close" not in prices[0], "Misleading provisional CSV"
    price_dates = index.get("price_dates", [])
    closing_rows = 0
    if price_dates:
        content = read("close-history.csv")
        assert hashlib.sha256(content.encode()).hexdigest() == index["close_history_sha256"], (
            "Closing-price CSV differs from this publication"
        )
        assert price_dates == sorted(set(price_dates)), "Duplicate or unordered price dates"
        seen = set()
        for row in csv.DictReader(io.StringIO(content)):
            key = (row["trade_date"], row["ticker"])
            assert key not in seen, "Duplicate closing price"
            seen.add(key)
            assert row["trade_date"] in price_dates, "Unexpected closing-price date"
            assert row["currency"] == "USD" and row["source"] == "yahoo"
            assert math.isfinite(float(row["close"])) and float(row["close"]) > 0
            closing_rows += 1
    return {
        "state": "ok",
        "latest_date": dates[-1],
        "provisional": bool(provisional),
        "closing_days": len(closed),
        "price_days": len(price_dates),
        "closing_price_rows": closing_rows,
        "instruments": len(rows),
        "tickers": len(seen_tickers),
        "publication_id": index.get("publication_id"),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("location", help="Export directory or URL ending in /data")
    parser.add_argument("--publication-id")
    parser.add_argument("--attempts", type=int, default=1)
    args = parser.parse_args()
    for attempt in range(args.attempts):
        try:
            print(json.dumps(verify(args.location, args.publication_id)))
            break
        except Exception as exc:
            if attempt + 1 == args.attempts:
                raise
            print(f"Publication check {attempt + 1} pending: {exc}", flush=True)
            time.sleep(15)
