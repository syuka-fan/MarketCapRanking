import csv
import hashlib
import json
import shutil
import sqlite3
import tempfile
from datetime import date
from pathlib import Path

from marketcap.calendar import previous_session, sessions
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
    company_index: dict[str, dict] = {}
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
            quotes.setdefault(quote["company_id"], []).append(quote)
        rows = []
        for rank in snapshot["rankings"]:
            company_id = rank["company_id"]
            change = previous[company_id] - rank["rank"] if company_id in previous else None
            change_state = (
                "known"
                if company_id in previous
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
                    "prices": [{**q, "close": float(q["close"])} for q in quotes[company_id]],
                }
            )
            company_index[company_id] = {
                "id": company_id,
                "name": rank["company_name"],
                "tickers": sorted(
                    set(company_index.get(company_id, {}).get("tickers", []))
                    | {q["ticker"] for q in quotes[company_id]}
                ),
            }
            point = {
                "rank": rank["rank"],
                "market_cap_usd": float(rank["market_cap_usd"]),
                "prices": [
                    {"ticker": q["ticker"], "close": float(q["close"])} for q in quotes[company_id]
                ],
            }
            if not is_provisional:
                db.execute(
                    "INSERT INTO history VALUES (?, ?, ?)",
                    (company_id, str(day), json.dumps(point)),
                )
        atomic_json(
            destination / "days" / f"{day}.json",
            {"date": day.isoformat(), "is_final_close": not is_provisional, "rows": rows},
        )
        prior_day = day
        previous_ranks = {r["company_id"]: r["rank"] for r in snapshot["rankings"]}
        latest = snapshot
    axis_dates = list(sessions(closed_dates[0], closed_dates[-1])) if closed_dates else []
    for company_id in company_index:
        points = {
            day: json.loads(point)
            for day, point in db.execute(
                "SELECT day, point FROM history WHERE company = ? ORDER BY day", (company_id,)
            )
        }
        filename = hashlib.sha256(company_id.encode()).hexdigest()[:24] + ".json"
        company_index[company_id]["history_file"] = filename
        atomic_json(destination / "companies" / filename, points)
    exchanges = latest["policy"]["exchanges"] if latest else ["XNYS", "XNAS", "XASE"]
    exchange_names = {"XNYS": "NYSE", "XNAS": "Nasdaq", "XASE": "NYSE American"}
    scope = " · ".join(exchange_names[e] for e in exchanges)
    atomic_json(
        destination / "index.json",
        {
            "schema_version": 1,
            "publication_id": hashlib.sha256(
                json.dumps({"status": status, "latest": latest}, sort_keys=True).encode()
            ).hexdigest(),
            "dates": [str(d) for d in dates],
            "closed_dates": [str(d) for d in closed_dates],
            "provisional_date": provisional["trade_date"] if provisional else None,
            "provisional_at": provisional["collected_at"] if provisional else None,
            "axis_dates": [str(d) for d in axis_dates],
            "status": status,
            "is_demo": latest["is_demo"] if latest else False,
            "source": latest["source"] if latest else None,
            "coverage": latest.get("coverage") if latest else None,
            "method": (
                "장중·잠정 가격과 대표 티커의 Yahoo 기업 시가총액 (종가 이력에서 제외)"
                if provisional
                else "본장 종료 후 대표 티커의 Yahoo 기업 시가총액 (복수 티커 합산 없음)"
                if latest and latest["source"] == "yahoo"
                else "가상 데이터의 기업별 시가총액"
            ),
            "scope": f"{scope} / Yahoo·Nasdaq 명부에서 확인되는 USD 보통주 / ADR·ETF 제외",
            "companies": list(company_index.values()),
        },
    )
    if provisional:
        for filename, source, columns in (
            (
                "rankings",
                provisional["rankings"],
                ["company_name", "canonical_ticker", "rank", "market_cap_usd"],
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
