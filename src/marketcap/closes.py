"""Incremental daily closes, inspired by syuka-fan/stock (see THIRD_PARTY_NOTICES).

Yahoo historical Close is split-adjusted even with auto_adjust=False. These
series are independent of the daily captured prices used for market-cap ranks.
"""

import fcntl
import json
import math
import os
import re
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

from marketcap.calendar import NEW_YORK, latest_completed, sessions
from marketcap.models import DataError, Settings
from marketcap.providers.yahoo import BudgetSession, RequestBudget
from marketcap.storage import atomic_json

DEFAULT_START = date(1990, 1, 1)
OVERLAP_DAYS = 7
COLUMNS = [
    "company_name",
    "ticker",
    "close",
    "trade_date",
    "open",
    "high",
    "low",
    "volume",
    "stock_splits",
    "currency",
    "source",
]
NUMERIC = ["close", "open", "high", "low", "volume", "stock_splits"]


def read_symbols(path: Path, selected: str | None = None) -> dict[str, str]:
    document = json.loads(path.read_text(encoding="utf-8"))
    symbols = document.get("us") if isinstance(document, dict) else None
    if not isinstance(symbols, dict) or not symbols:
        raise DataError('Symbols file must contain a nonempty "us" ticker-to-name mapping')
    if any(
        not re.fullmatch(r"[A-Z][A-Z0-9-]{0,19}", ticker)
        or not isinstance(name, str)
        or not name.strip()
        for ticker, name in symbols.items()
    ):
        raise DataError("Use US Yahoo tickers (BRK-B, not BRK.B) and nonempty company names")
    if selected:
        requested = list(dict.fromkeys(t.strip().upper() for t in selected.split(",")))
        missing = set(requested) - symbols.keys()
        if missing:
            raise DataError(f"Add these tickers to {path} first: {', '.join(sorted(missing))}")
        return {ticker: symbols[ticker] for ticker in requested}
    return symbols


class YahooHistory:
    def __init__(self, settings: Settings):
        self.budget = RequestBudget(settings)
        self.session = BudgetSession(self.budget)

    def fetch(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        try:
            instrument = yf.Ticker(ticker, session=self.session)
            frame = instrument.history(
                start=start.isoformat(),
                end=(end + timedelta(days=1)).isoformat(),  # Yahoo end is exclusive.
                interval="1d",
                auto_adjust=False,
                back_adjust=False,
                prepost=False,
                actions=True,
                repair=False,
                timeout=25,
                raise_errors=True,
            )
            metadata = instrument.history_metadata
            if (
                metadata.get("currency") != "USD"
                or metadata.get("exchangeTimezoneName") != "America/New_York"
                or metadata.get("instrumentType") not in {"EQUITY", "ETF"}
            ):
                raise DataError(f"{ticker}: expected a US-listed USD stock or ETF")
            return frame
        except DataError:
            raise
        except Exception:
            raise DataError(f"{ticker}: Yahoo daily history unavailable; retry later") from None


def normalize(frame: pd.DataFrame, ticker: str, name: str, start: date, end: date) -> pd.DataFrame:
    if frame is None or frame.empty:
        raise DataError(f"{ticker}: no completed-session prices returned")
    frame = frame.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        # Also accept the format returned by the reference project's yf.download().
        frame.columns = frame.columns.get_level_values(0)
    required = ["Open", "High", "Low", "Close", "Volume"]
    if not set(required) <= set(frame.columns) or frame.columns.duplicated().any():
        raise DataError(f"{ticker}: invalid daily history columns")
    index = pd.to_datetime(frame.index)
    if index.tz is not None:
        index = index.tz_convert(NEW_YORK)
    frame["trade_date"] = [d.isoformat() for d in index.date]
    valid_dates = {d.isoformat() for d in sessions(start, end)}
    frame = frame[frame.trade_date.isin(valid_dates)].copy()
    # Corporate-action-only rows can have no price; never turn them into zero closes.
    frame = frame.dropna(subset=["Close"])
    if frame.empty:
        raise DataError(f"{ticker}: no completed-session prices returned")
    frame = frame.rename(columns={key: key.lower() for key in required})
    frame["stock_splits"] = frame.get("Stock Splits", 0)
    for column in NUMERIC:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if not frame[column].map(math.isfinite).all():
            raise DataError(f"{ticker}: invalid {column} values")
        minimum = 0 if column in {"volume", "stock_splits"} else 1e-15
        if (frame[column] < minimum).any():
            raise DataError(f"{ticker}: invalid {column} values")
    frame["company_name"] = name
    frame["ticker"] = ticker
    frame["currency"] = "USD"
    frame["source"] = "yahoo_daily_close_split_adjusted"
    return frame[COLUMNS].drop_duplicates("trade_date", keep="last").sort_values("trade_date")


def read_existing(path: Path, ticker: str) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=COLUMNS)
    frame = pd.read_csv(path, dtype={"trade_date": str})
    if list(frame.columns) != COLUMNS or frame.empty or not frame.ticker.eq(ticker).all():
        raise DataError(f"{ticker}: invalid existing CSV; preserve it and repair before retrying")
    if frame.trade_date.duplicated().any():
        raise DataError(f"{ticker}: duplicate dates in existing CSV")
    for value in frame.trade_date:
        date.fromisoformat(value)
    return frame.sort_values("trade_date")


def write_csv(path: Path, frame: pd.DataFrame) -> bool:
    content = frame.to_csv(index=False, float_format="%.12g", lineterminator="\n").encode()
    if path.exists() and path.read_bytes() == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return True


def adjustment_changed(old: pd.DataFrame, fresh: pd.DataFrame) -> bool:
    if old.empty:
        return False
    if fresh.loc[fresh.trade_date > old.trade_date.max(), "stock_splits"].ne(0).any():
        return True
    shared = old.merge(fresh, on="trade_date", suffixes=("_old", "_new"))
    return any(
        not math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-8)
        for a, b in zip(shared.close_old, shared.close_new, strict=True)
    )


def download_closes(
    provider: YahooHistory,
    symbols: dict[str, str],
    root: Path,
    *,
    start: date | None = None,
    end: date | None = None,
    refresh: bool = False,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(UTC)
    cutoff = latest_completed(now)
    end = min(end, cutoff) if end else cutoff
    if start and start > end:
        raise DataError("Start date is after the last requested completed US session")
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".closes.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DataError("Another downloader is writing to this data directory") from None
        state_path = root / "download_state.json"
        # CSV is authoritative; a lost/corrupt state file must not restart the full download.
        try:
            state = json.loads(state_path.read_text())
            if not isinstance(state, dict):
                state = {}
        except (FileNotFoundError, ValueError):
            state = {}
        report = {
            "state": "running",
            "source": "yahoo",
            "checked_at": now.isoformat(),
            "completed_through": end.isoformat(),
            "requested": len(symbols),
            "updated": [],
            "unchanged": [],
            "failed": {},
            "skipped": [],
        }
        atomic_json(root / "download_status.json", report)
        for ticker, name in symbols.items():
            if provider.budget.stop_reason:
                report["skipped"].append(ticker)
                continue
            path = root / "us_daily" / f"{ticker}.csv"
            try:
                old = read_existing(path, ticker)
                if not old.empty and date.fromisoformat(old.trade_date.max()) > cutoff:
                    raise DataError(f"{ticker}: existing CSV contains an unfinished session")
                if start:
                    first = start
                elif old.empty:
                    first = DEFAULT_START
                elif refresh:
                    first = date.fromisoformat(old.trade_date.min())
                else:
                    first = date.fromisoformat(old.trade_date.max()) - timedelta(days=OVERLAP_DAYS)
                if first > end or not sessions(first, end):
                    report["unchanged"].append(ticker)
                    continue
                fresh = normalize(provider.fetch(ticker, first, end), ticker, name, first, end)
                # Splits rewrite Yahoo's older Close values too. Keep one adjustment basis.
                if adjustment_changed(old, fresh):
                    first = min(first, date.fromisoformat(old.trade_date.min()))
                    full_end = max(end, date.fromisoformat(old.trade_date.max()))
                    fresh = normalize(
                        provider.fetch(ticker, first, full_end), ticker, name, first, full_end
                    )
                    if not set(old.trade_date) <= set(fresh.trade_date):
                        raise DataError(f"{ticker}: revised history is incomplete; kept old CSV")
                merged = fresh if old.empty else pd.concat([old, fresh], ignore_index=True)
                merged = merged.drop_duplicates("trade_date", keep="last").sort_values("trade_date")
                merged["company_name"] = name
                changed = write_csv(path, merged[COLUMNS])
                state[ticker] = {
                    "company_name": name,
                    "source": "yahoo",
                    "rows": len(merged),
                    "first_date": merged.trade_date.min(),
                    "last_date": merged.trade_date.max(),
                    "out_path": f"us_daily/{ticker}.csv",
                    "checked_at": now.isoformat(),
                    "price_basis": "split_adjusted_close_not_dividend_adjusted",
                }
                atomic_json(state_path, state)
                report["updated" if changed else "unchanged"].append(ticker)
            except (DataError, OSError, ValueError) as exc:
                report["failed"][ticker] = str(exc)
            # Keep progress reviewable even when a later ticker fails or the job times out.
            report["http_requests"] = provider.budget.calls
            atomic_json(root / "download_status.json", report)
        report["state"] = "incomplete" if report["failed"] or report["skipped"] else "ok"
        report["http_requests"] = provider.budget.calls
        atomic_json(root / "download_status.json", report)
        return report
