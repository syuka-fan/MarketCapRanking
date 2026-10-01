from dataclasses import replace
from datetime import date

import pytest
from test_yahoo import OTHER, bundle, quote

from marketcap.models import DataError
from marketcap.pipeline import run
from marketcap.providers.supplements import ETF_COLUMNS, STOCK_COLUMNS, etf_units, kis_rows
from marketcap.providers.yahoo import YahooProvider, select_universe, ticker_capitalization
from marketcap.storage import Store


def master_row(ticker, name, english, dr="N", kind="2"):
    row = ["US", "21", "NYS", "뉴욕", ticker, "NYS" + ticker, name, english, kind, "USD"]
    row += ["4", "", "100", "1", "1", "930", "1600", dr, "", "000", "0", "0", "", ""]
    return "\t".join(row)


def test_share_classes_rank_independently_of_issuer_cap(tmp_path, settings, now, monkeypatch):
    data = bundle()
    data["quotes"] = [
        quote(
            "ALPHA",
            regularMarketPrice=20,
            sharesOutstanding=30,
            marketCap=999999,
            impliedSharesOutstanding=50000,
        ),
        quote(
            "ALPHB",
            regularMarketPrice=15,
            sharesOutstanding=10,
            marketCap=999999,
            impliedSharesOutstanding=50000,
        ),
        quote("BETA", regularMarketPrice=10, sharesOutstanding=40),
    ]
    provider = YahooProvider(settings, tmp_path)
    monkeypatch.setattr(provider, "fetch_bundle", lambda day: data)
    run(provider, settings, tmp_path, now=now)
    ranks = Store(tmp_path).load(date(2026, 9, 30))["rankings"]
    assert [(r["ticker"], r["market_cap_usd"], r["rank"]) for r in ranks] == [
        ("ALPHA", "600.00", 1),
        ("BETA", "400.00", 2),
        ("ALPHB", "150.00", 3),
    ]
    assert ranks[0]["issuer_id"] == ranks[2]["issuer_id"]
    assert ranks[0]["instrument_id"] != ranks[2]["instrument_id"]


def test_adr_without_english_suffix_and_etf_use_their_own_units(settings):
    data = bundle()
    data["otherlisted"] = OTHER + (
        "TSM|Taiwan Semiconductor Manufacturing Company Ltd.|N|TSM|N|100|N|TSM\n"
        "VOO|Vanguard S&P 500 ETF|P|VOO|Y|100|N|VOO\n"
        "PREF|Example Preferred Stock|N|PREF|N|100|N|PREF\n"
        "NOTE|Example Exchange Traded Notes ETN|P|NOTE|Y|100|N|NOTE\n"
    )
    data["kis_directories"] = {"nys": master_row("TSM", "TSMC(ADR)", "TSMC SPON ADS", "Y")}
    data["quotes"] += [
        quote("TSM", regularMarketPrice=450, sharesOutstanding=5, adrRatio=5),
        quote(
            "VOO", quoteType="ETF", regularMarketPrice=700, sharesOutstanding=1, netAssets=999999999
        ),
    ]
    data["etf_shares"] = {
        "columns": ETF_COLUMNS,
        "totalCount": 1,
        "data": [{"s": "AMEX:VOO", "d": ["VOO", "fund", "etf", 100, "USD", "AMEX"]}],
    }
    data["stock_shares"] = {
        "columns": STOCK_COLUMNS,
        "totalCount": 2,
        "data": [
            {"s": "NASDAQ:ALPHA", "d": ["ALPHA", "stock", "common", 80, "USD", "NASDAQ"]},
            {"s": "NYSE:TSM", "d": ["TSM", "dr", "", 5, "USD", "NYSE"]},
        ],
    }
    selected, listings, _ = select_universe(
        data, replace(settings, security_types=("CS", "ADR", "ETF"))
    )
    assert listings["TSM"]["security_type"] == "ADR"
    assert listings["TSM"]["display_name"] == "TSMC(ADR)"
    assert ticker_capitalization(selected["TSM"])["market_cap_usd"] == "2250.00"
    assert ticker_capitalization(selected["ALPHA"])["market_cap_usd"] == "800.00"
    assert ticker_capitalization(selected["ALPHA"])["shares_source"] == "TradingView"
    assert ticker_capitalization(selected["VOO"])["market_cap_usd"] == "70000.00"
    assert ticker_capitalization(selected["VOO"])["shares_source"] == "TradingView"
    assert "PREF" not in listings and "NOTE" not in listings


def test_missing_etf_units_never_fall_back_to_company_cap_or_aum():
    with pytest.raises(DataError, match="shares outstanding"):
        ticker_capitalization(quote("VOO", sharesOutstanding=None, marketCap=1e12, netAssets=2e12))
    assert (
        kis_rows(master_row("SKHY", "SK하이닉스(ADR)", "SK HYNIX SPON ADS"))["SKHY"][
            "security_type"
        ]
        == "ADR"
    )


def test_etf_supplement_rejects_incomplete_duplicate_and_ambiguous_rows():
    row = {"s": "AMEX:VOO", "d": ["VOO", "fund", "etf", 100, "USD", "AMEX"]}
    with pytest.raises(DataError, match="Incomplete"):
        etf_units({"columns": ETF_COLUMNS, "totalCount": 2, "data": [row]})
    with pytest.raises(DataError, match="Duplicate"):
        etf_units({"columns": ETF_COLUMNS, "totalCount": 2, "data": [row, row]})
    with pytest.raises(DataError, match="Ambiguous"):
        etf_units(
            {"columns": ETF_COLUMNS, "totalCount": 2, "data": [row, {**row, "s": "NASDAQ:VOO"}]}
        )


def test_equity_and_etf_screeners_are_both_exhausted(tmp_path, settings, monkeypatch):
    provider = YahooProvider(replace(settings, security_types=("CS", "ADR", "ETF")), tmp_path)
    calls = []

    def screen(offset, *, etf=False):
        calls.append((etf, offset))
        if not etf:
            return {"total": 2, "quotes": [quote("ALPHA"), quote("ETF")]}
        return {"total": 2, "quotes": [quote("ETF" if offset == 0 else "NEXT", quoteType="ETF")]}

    monkeypatch.setattr(provider, "screen", screen)
    monkeypatch.setattr(provider, "_text", lambda url: "directory")
    monkeypatch.setattr("marketcap.providers.yahoo.fetch_supplements", lambda *args: {})
    result = provider.fetch_universe()
    assert calls == [(False, 0), (True, 0), (True, 1)]
    assert {q["symbol"] for q in result["quotes"]} == {"ALPHA", "ETF", "NEXT"}
    assert next(q for q in result["quotes"] if q["symbol"] == "ETF")["quoteType"] == "ETF"


def test_etf_retry_keeps_already_validated_stock_pages(tmp_path, settings, monkeypatch):
    provider = YahooProvider(replace(settings, security_types=("CS", "ETF")), tmp_path)
    calls = []
    etf_pages = iter(
        [
            {"total": 2, "quotes": [quote("ETF")]},
            {"total": 2, "quotes": [quote("ETF")]},
            {"total": 2, "quotes": [quote("ETF"), quote("NEXT")]},
        ]
    )

    def screen(offset, *, etf=False):
        calls.append((etf, offset))
        return next(etf_pages) if etf else {"total": 1, "quotes": [quote("ALPHA")]}

    monkeypatch.setattr(provider, "screen", screen)
    monkeypatch.setattr(provider, "_text", lambda url: "directory")
    monkeypatch.setattr("marketcap.providers.yahoo.fetch_supplements", lambda *args: {})
    monkeypatch.setattr("marketcap.providers.yahoo.time.sleep", lambda seconds: None)
    assert len(provider.fetch_universe()["quotes"]) == 3
    assert calls == [(False, 0), (True, 0), (True, 1), (True, 0)]
