from decimal import Decimal

from marketcap.models import DataError


def rank_instruments(rows: list[dict]) -> list[dict]:
    ids = [r["instrument_id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise DataError("Duplicate instrument in rankings")
    ordered = sorted(rows, key=lambda r: (-Decimal(r["market_cap_usd"]), r["instrument_id"]))
    previous_cap = None
    rank = 0
    for index, row in enumerate(ordered, 1):
        cap = Decimal(row["market_cap_usd"])
        if cap != previous_cap:
            rank = index
        row["rank"] = rank
        previous_cap = cap
    return ordered
