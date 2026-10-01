import csv
import hashlib
import json
import shutil
import sqlite3
import tempfile
from datetime import date
from pathlib import Path

from marketcap.calendar import previous_session, sessions
from marketcap.market_closes import export_closes
from marketcap.storage import Store, atomic_json


def export_site(root: Path, destination: Path) -> None:
    # Spill history to a temporary database; do not keep every daily snapshot in RAM.
    with tempfile.TemporaryDirectory(prefix="marketcap-export-") as temporary:
        with sqlite3.connect(Path(temporary) / "history.db") as db:
            db.execute(
                "CREATE TABLE history (company TEXT, day TEXT, point TEXT, "
                "PRIMARY KEY (company, day))"
            )
            _export(root, destination, db)


def _export(root: Path, destination: Path, db: sqlite3.Connection) -> None:
    store = Store(root)
    closed_dates = store.dates()
    provisional_path = root / "provisional.json"
    provisional = json.loads(provisional_path.read_text()) if provisional_path.exists() else None
    if provisional and closed_dates and provisional["trade_date"] <= str(closed_dates[-1]):
        provisional = None
    dates = closed_dates + ([date.fromisoformat(provisional["trade_date"])] if provisional else [])
    status_path = root / "status.json"
    status = (
        json.loads(status_path.read_text())
        if status_path.exists()
        else {
            "state": "empty",
            "latest_trade_date": None,
            "last_success_at": None,
        }
    )
    destination.mkdir(parents=True, exist_ok=True)
    price_dates = export_closes(root, destination)
    close_history_hash = (
        hashlib.sha256((destination / "close-history.csv").read_bytes()).hexdigest()
        if price_dates
        else None
    )
    close_status_path = root / "close-status.json"
    close_status = json.loads(close_status_path.read_text()) if close_status_path.exists() else {}
    close_summary = {
        key: close_status[key]
        for key in (
            "state",
            "attempted_at",
            "completed_at",
            "start_date",
            "end_date",
            "requested_tickers",
            "processed_tickers",
            "counts_by_date",
            "error",
        )
        if key in close_status
    }
    close_summary["missing_counts_by_date"] = {
        day: len(tickers) for day, tickers in close_status.get("missing_by_date", {}).items()
    }
    instrument_index: dict[str, dict] = {}
    prior_day = None
    previous_ranks: dict[str, int] = {}
    latest = None
    for day in dates:
        is_provisional = bool(provisional and str(day) == provisional["trade_date"])
        snapshot = provisional if is_provisional else store.load(day)
        has_prior = prior_day == previous_session(day)
        previous = previous_ranks if has_prior else {}
        quotes: dict[str, list] = {}
        for quote in snapshot["prices"]:
            quotes.setdefault(quote["instrument_id"], []).append(quote)
        rows = []
        for rank in snapshot["rankings"]:
            instrument_id = rank["instrument_id"]
            change = previous[instrument_id] - rank["rank"] if instrument_id in previous else None
            change_state = (
                "known"
                if instrument_id in previous
                else "new"
                if has_prior
                else "baseline"
                if day == dates[0]
                else "gap"
            )
            rows.append(
                {
                    **rank,
                    "market_cap_usd": float(rank["market_cap_usd"]),
                    "rank_change": change,
                    "change_state": change_state,
                    "prices": [{**q, "close": float(q["close"])} for q in quotes[instrument_id]],
                }
            )
            instrument_index[instrument_id] = {
                "id": instrument_id,
                "name": rank["company_name"],
                "tickers": sorted(
                    set(instrument_index.get(instrument_id, {}).get("tickers", []))
                    | {q["ticker"] for q in quotes[instrument_id]}
                ),
            }
            point = {
                "rank": rank["rank"],
                "market_cap_usd": float(rank["market_cap_usd"]),
                "prices": [
                    {"ticker": q["ticker"], "close": float(q["close"])}
                    for q in quotes[instrument_id]
                ],
            }
            if not is_provisional:
                db.execute(
                    "INSERT INTO history VALUES (?, ?, ?)",
                    (instrument_id, str(day), json.dumps(point)),
                )
        atomic_json(
            destination / "days" / f"{day}.json",
            {"date": day.isoformat(), "is_final_close": not is_provisional, "rows": rows},
        )
        prior_day = day
        previous_ranks = {r["instrument_id"]: r["rank"] for r in snapshot["rankings"]}
        latest = snapshot
    axis_dates = list(sessions(closed_dates[0], closed_dates[-1])) if closed_dates else []
    for instrument_id in instrument_index:
        points = {
            day: json.loads(point)
            for day, point in db.execute(
                "SELECT day, point FROM history WHERE company = ? ORDER BY day", (instrument_id,)
            )
        }
        filename = hashlib.sha256(instrument_id.encode()).hexdigest()[:24] + ".json"
        instrument_index[instrument_id]["history_file"] = filename
        atomic_json(destination / "instruments" / filename, points)
    exchanges = latest["policy"]["exchanges"] if latest else ["XNYS", "XNAS", "XASE"]
    exchange_names = {
        "XNYS": "NYSE",
        "XNAS": "Nasdaq",
        "XASE": "NYSE American",
        "ARCX": "NYSE Arca",
        "BATS": "Cboe BZX",
    }
    scope = " · ".join(exchange_names[e] for e in exchanges)
    atomic_json(
        destination / "index.json",
        {
            "schema_version": 2,
            "publication_id": hashlib.sha256(
                json.dumps(
                    {
                        "status": status,
                        "latest": latest,
                        "closing_prices": close_summary,
                        "close_history_sha256": close_history_hash,
                    },
                    sort_keys=True,
                ).encode()
            ).hexdigest(),
            "dates": [str(d) for d in dates],
            "closed_dates": [str(d) for d in closed_dates],
            "price_dates": price_dates,
            "close_history_file": "close-history.csv" if price_dates else None,
            "close_history_sha256": close_history_hash,
            "close_status": close_summary,
            "provisional_date": provisional["trade_date"] if provisional else None,
            "provisional_at": provisional["collected_at"] if provisional else None,
            "axis_dates": [str(d) for d in axis_dates],
            "status": status,
            "is_demo": latest["is_demo"] if latest else False,
            "source": latest["source"] if latest else "yahoo" if price_dates else None,
            "coverage": latest.get("coverage") if latest else None,
            "method": (
                "장중·잠정 티커별 가격 × 해당 티커 발행수 (종가 이력에서 제외)"
                if provisional
                else "티커별 본장 종가 × 해당 티커 발행수 (보통주·ADR·ETF, 티커 병합 없음)"
                if latest and latest["source"] == "yahoo"
                else "가상 데이터의 티커별 시가총액"
                if latest and latest["is_demo"]
                else "확인된 종가 이력 (시가총액·순위 원본 미확인)"
            ),
            "scope": f"{scope} / Yahoo·Nasdaq 명부에서 확인되는 USD 보통주·ADR·ETF",
            "instruments": list(instrument_index.values()),
        },
    )
    if provisional:
        for filename, source, columns in (
            (
                "rankings",
                provisional["rankings"],
                [
                    "company_name",
                    "ticker",
                    "security_type",
                    "rank",
                    "market_cap_usd",
                    "shares_outstanding",
                    "shares_source",
                    "method",
                ],
            ),
            ("prices", provisional["prices"], ["company_name", "ticker", "price", "quote_date"]),
        ):
            with (destination / f"latest-{filename}.csv").open(
                "w", newline="", encoding="utf-8"
            ) as stream:
                writer = csv.DictWriter(
                    stream, fieldnames=[*columns, "trade_date", "captured_at", "is_final_close"]
                )
                writer.writeheader()
                for row in source:
                    writer.writerow(
                        {
                            **{
                                key: row["close"] if key == "price" else row[key] for key in columns
                            },
                            "trade_date": provisional["trade_date"],
                            "captured_at": provisional["collected_at"],
                            "is_final_close": False,
                        }
                    )
    elif latest:
        pointer_dir = root / "snapshots" / latest["trade_date"]
        pointer = json.loads((pointer_dir / "current.json").read_text())
        for filename in ("prices.csv", "rankings.csv"):
            shutil.copyfile(
                pointer_dir / "revisions" / pointer["revision"] / filename,
                destination / f"latest-{filename}",
            )
