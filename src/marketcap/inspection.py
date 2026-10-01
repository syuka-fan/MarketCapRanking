"""Review full-universe discovery without publishing an intraday closing snapshot."""

import csv
from collections import Counter
from datetime import datetime

from marketcap.calendar import NEW_YORK
from marketcap.identity import identify
from marketcap.models import DataError, positive
from marketcap.providers.yahoo import (
    YahooProvider,
    issuer_name,
    select_universe,
    ticker_capitalization,
)
from marketcap.ranking import rank_instruments
from marketcap.storage import atomic_json


def inspect_universe(provider: YahooProvider, bundle: dict | None = None) -> dict:
    bundle = bundle if bundle is not None else provider.fetch_universe()
    selected, listings, coverage = select_universe(bundle, provider.settings)
    valid = {}
    excluded = []
    for ticker, quote in selected.items():
        try:
            if quote.get("currency") != "USD" or quote.get("quoteType") not in {"EQUITY", "ETF"}:
                raise DataError("Not a USD equity")
            ticker_capitalization(quote)
            positive(quote.get("regularMarketPrice"), "price")
            issuer_name(quote)
        except DataError as exc:
            excluded.append({"ticker": ticker, "reason": str(exc)})
        else:
            valid[ticker] = quote
    captured = datetime.fromisoformat(bundle["captured_at"])
    day = captured.astimezone(NEW_YORK).date().isoformat()
    securities = identify(provider.security_rows(valid, listings, day), provider.settings)
    rows = []
    for instrument_id, members in {s.security_id: [s] for s in securities}.items():
        representative = members[0]
        quote = valid[representative.ticker]
        rows.append(
            {
                "company_name": representative.company_name,
                "ticker": representative.ticker,
                "regular_price": str(quote["regularMarketPrice"]),
                **ticker_capitalization(quote),
                "security_type": representative.share_type,
                "instrument_id": instrument_id,
                "tickers": "|".join(sorted(s.ticker for s in members)),
                "captured_at": bundle["captured_at"],
                "is_final_close": False,
            }
        )
    ranked = rank_instruments(rows)
    report = {
        "scope": "universe_inspection_not_daily_closing_history",
        "is_final_close": False,
        "captured_at": bundle["captured_at"],
        **coverage,
        "rankable_tickers": len(valid),
        "instrument_count": len(ranked),
        "excluded_quotes": excluded,
        "market_states": dict(Counter(q.get("marketState", "unknown") for q in selected.values())),
        "source_http_requests": bundle.get("http_requests"),
        "http_requests_this_run": provider.requests_made,
        "top_10": ranked[:10],
    }
    output = provider.root / "inspection"
    atomic_json(output / "universe.json", bundle)
    with (output / "rankings-preview.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=[*ranked[0]])
        writer.writeheader()
        writer.writerows(ranked)
    atomic_json(output / "report.json", report)
    return report
