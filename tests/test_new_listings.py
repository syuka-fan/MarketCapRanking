"""Exercise changes across trading days using the real Yahoo ranking pipeline."""

import json
from datetime import date, timedelta

from marketcap.calendar import sessions
from marketcap.export import export_site
from marketcap.pipeline import run
from marketcap.providers.yahoo import YahooProvider
from marketcap.storage import Store


def collect_session(root, settings, monkeypatch, day, additions=()):
    close = sessions(day, day)[day]
    captured = close + timedelta(hours=4)
    quotes = [
        {
            "symbol": f"BASE{i:03}",
            "longName": f"Established Company {i} Inc.",
            "marketCap": (i + 1) * 1000,
            "regularMarketPrice": 10,
        }
        for i in range(80)
    ] + list(additions)
    quotes = [
        {
            "marketState": "POSTPOST",
            "regularMarketTime": int(close.timestamp()),
            "currency": "USD",
            "quoteType": "EQUITY",
            **quote,
        }
        for quote in quotes
    ]
    # Keep both directory formats in the real selection path.
    nasdaq = "Symbol|Security Name|Test Issue|ETF\n" + "\n".join(
        f"{q['symbol']}|{q['longName']} - Common Stock|N|N" for q in quotes[1:]
    )
    other = (
        "ACT Symbol|Security Name|Exchange|Test Issue|ETF\n"
        "BASE000|Established Company 0 Inc. Common Stock|N|N|N\n"
    )
    bundle = {
        "trade_date": str(day),
        "captured_at": captured.isoformat(),
        "quotes": quotes,
        "nasdaqlisted": nasdaq,
        "otherlisted": other,
    }
    provider = YahooProvider(settings, root)
    monkeypatch.setattr(provider, "fetch_bundle", lambda requested: bundle)
    run(provider, settings, root, now=captured)
    return Store(root).load(day)


def new_issuer(**changes):
    return {
        "symbol": "NEWCO",
        "longName": "Newly Listed Company Inc.",
        "marketCap": 1_000_000,
        "regularMarketPrice": 25,
        **changes,
    }


def test_new_company_is_discovered_ranked_and_marked_new_without_changing_old_history(
    tmp_path, settings, monkeypatch
):
    first = date(2026, 9, 28)
    second = date(2026, 9, 29)
    before = collect_session(tmp_path, settings, monkeypatch, first)
    after = collect_session(tmp_path, settings, monkeypatch, second, [new_issuer()])
    assert len(before["rankings"]) == 80
    assert len(after["rankings"]) == 81
    assert len(after["prices"]) == 81
    assert after["rankings"][0]["canonical_ticker"] == "NEWCO"
    assert after["rankings"][0]["rank"] == 1
    assert Store(tmp_path).load(first) == before

    output = tmp_path / "site"
    export_site(tmp_path, output)
    rows = json.loads((output / f"days/{second}.json").read_text())["rows"]
    new = next(row for row in rows if row["canonical_ticker"] == "NEWCO")
    assert new["change_state"] == "new"
    assert new["rank_change"] is None
    assert all(row["rank_change"] == -1 for row in rows if row != new)
    index = json.loads((output / "index.json").read_text())
    company = next(c for c in index["companies"] if c["id"] == new["company_id"])
    history = json.loads((output / "companies" / company["history_file"]).read_text())
    assert list(history) == [str(second)]  # Never fabricate ranks before discovery.


def test_new_share_class_joins_existing_company_without_double_counting_cap(
    tmp_path, settings, monkeypatch
):
    before = collect_session(tmp_path, settings, monkeypatch, date(2026, 9, 28))
    extra = new_issuer(
        symbol="ZCLASS",
        longName="Established Company 0 Inc.",
        marketCap=900,
        regularMarketPrice=9,
    )
    after = collect_session(tmp_path, settings, monkeypatch, date(2026, 9, 29), [extra])
    assert len(after["rankings"]) == 80
    assert len(after["prices"]) == 81
    existing = next(s for s in before["securities"] if s["ticker"] == "BASE000")
    added = next(s for s in after["securities"] if s["ticker"] == "ZCLASS")
    assert added["company_id"] == existing["company_id"]
    ranking = next(r for r in after["rankings"] if r["company_id"] == added["company_id"])
    assert ranking["market_cap_usd"] == "1000.00"


def test_new_listing_with_delayed_market_cap_is_retried_on_next_session(
    tmp_path, settings, monkeypatch
):
    collect_session(tmp_path, settings, monkeypatch, date(2026, 9, 28))
    incomplete = collect_session(
        tmp_path, settings, monkeypatch, date(2026, 9, 29), [new_issuer(marketCap=None)]
    )
    assert len(incomplete["rankings"]) == 80
    assert incomplete["coverage"]["excluded_quotes"][0]["ticker"] == "NEWCO"
    assert incomplete["coverage"]["valid_quote_ratio"] >= 0.98
    complete = collect_session(tmp_path, settings, monkeypatch, date(2026, 9, 30), [new_issuer()])
    assert len(complete["rankings"]) == 81
    assert complete["rankings"][0]["canonical_ticker"] == "NEWCO"
    assert complete["coverage"]["excluded_quotes"] == []
    assert Store(tmp_path).load(date(2026, 9, 29)) == incomplete
