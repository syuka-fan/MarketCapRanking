import fcntl
import hashlib
import json
import shutil
from dataclasses import asdict
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, localcontext
from pathlib import Path

from marketcap.calendar import latest_completed, sessions
from marketcap.identity import identify
from marketcap.models import DataError, Security, Settings, positive
from marketcap.providers import Provider
from marketcap.ranking import rank_instruments
from marketcap.storage import Store, atomic_json

METHOD = "ticker_price_x_ticker_shares_outstanding_v2"


def validate_detail(detail: dict, representative: Security, day: str | None = None) -> None:
    if detail.get("ticker") != representative.ticker:
        raise DataError(f"{representative.ticker}: reference ticker mismatch")
    cik = str(detail.get("cik") or "")
    if representative.company_id.startswith("cik:") and (
        not cik.isdigit() or f"cik:{int(cik):010d}" != representative.company_id
    ):
        raise DataError(f"{representative.ticker}: reference company identity mismatch")
    if "market_cap_usd" in detail:
        if day and detail.get("market_cap_date") != day:
            raise DataError(f"{representative.ticker}: market capitalization date mismatch")
        positive(detail["market_cap_usd"], f"{representative.ticker} company market cap")
    else:
        positive(
            detail.get("weighted_shares_outstanding"), f"{representative.ticker} equivalent shares"
        )


def validate_quote(quote: dict, security: Security, day: str) -> None:
    if quote.get("from") != day or quote.get("symbol") != security.ticker:
        raise DataError(f"{security.ticker}: close date or ticker mismatch")
    positive(quote.get("close"), f"{security.ticker} regular close")


def collect_day(
    provider: Provider,
    settings: Settings,
    store: Store,
    day: date,
    now: datetime,
    refresh: bool = False,
) -> tuple[dict, dict]:
    label = day.isoformat()
    cache_namespace = hashlib.sha256(
        json.dumps({"source": provider.name, "policy": settings.policy()}, sort_keys=True).encode()
    ).hexdigest()[:16]
    cache_dir = store.root / "pending" / label / cache_namespace
    cache_dir.mkdir(parents=True, exist_ok=True)

    def cached(key: str, fetch, validate):
        # Hashed keys and fixed names avoid ticker-dependent filesystem paths.
        path = cache_dir / f"{key}.json"
        if path.exists() and not refresh:
            value = json.loads(path.read_text())
        else:
            value = fetch()
        try:
            validate(value)
        except DataError:
            path.unlink(missing_ok=True)
            raise
        atomic_json(path, value)
        return value

    rows = cached("universe", lambda: provider.tickers(label), lambda r: identify(r, settings))
    securities = identify(rows, settings)
    groups = {s.security_id: [s] for s in securities}
    earlier = [d for d in store.dates() if d < day]
    if earlier:
        prior_count = len(store.load(earlier[-1])["rankings"])
        if len(groups) < prior_count * settings.minimum_universe_ratio:
            (cache_dir / "universe.json").unlink(missing_ok=True)
            raise DataError(
                f"{label}: universe shrank unexpectedly; review coverage before publishing"
            )

    prices = []
    company_rows = []
    raw = {"universe": rows, "quotes": {}, "details": {}}
    for index, (instrument_id, members) in enumerate(sorted(groups.items())):
        representative = members[0]
        detail_key = "detail-" + hashlib.sha256(representative.ticker.encode()).hexdigest()
        detail = cached(
            detail_key,
            lambda s=representative: provider.details(s.ticker, label),
            lambda d, s=representative: validate_detail(d, s, label),
        )
        shares = (
            positive(detail["weighted_shares_outstanding"], "equivalent shares")
            if "weighted_shares_outstanding" in detail
            else None
        )
        company_name = (
            settings.company_names.get(representative.company_id) or representative.company_name
        )
        representative_close = None
        for security in members:
            quote_key = "quote-" + hashlib.sha256(security.ticker.encode()).hexdigest()
            quote = cached(
                quote_key,
                lambda s=security: provider.close(s.ticker, label),
                lambda q, s=security: validate_quote(q, s, label),
            )
            close = positive(quote.get("close"), f"{security.ticker} regular close")
            if security == representative:
                representative_close = close
            prices.append(
                {
                    "company_name": company_name,
                    "ticker": security.ticker,
                    "close": str(close),
                    "instrument_id": instrument_id,
                    "security_id": security.security_id,
                    "currency": "USD",
                }
            )
            raw["quotes"][security.ticker] = quote
        with localcontext() as ctx:
            ctx.prec = 40
            if "market_cap_usd" in detail:
                if (
                    positive(detail.get("market_cap_price"), "market cap price")
                    != representative_close
                ):
                    raise DataError("Price and market capitalization snapshots do not match")
                amount = positive(detail["market_cap_usd"], "market cap")
            else:
                amount = representative_close * shares
            cap = amount.quantize(positive("0.01", "precision"), rounding=ROUND_HALF_UP)
        company_rows.append(
            {
                "instrument_id": instrument_id,
                "company_name": company_name,
                "market_cap_usd": str(cap),
                "ticker": representative.ticker,
                "security_type": representative.share_type,
                "issuer_id": representative.company_id,
                "shares_outstanding": detail.get("shares_outstanding", str(shares or "")),
                "shares_source": detail.get("shares_source", provider.name),
                "method": detail.get("method", METHOD),
            }
        )
        raw["details"][representative.ticker] = detail
        if (index + 1) % 100 == 0:
            print(f"{label}: validated {index + 1}/{len(groups)} instruments", flush=True)
    return {
        "schema_version": 2,
        "trade_date": label,
        "collected_at": now.isoformat(),
        "source": provider.name,
        "is_demo": provider.name == "demo",
        "coverage": getattr(provider, "coverage", None),
        "policy": settings.policy(),
        "market_close_at": sessions(day, day)[day].isoformat(),
        "securities": [asdict(s) for s in securities],
        "prices": prices,
        "rankings": rank_instruments(company_rows),
    }, raw


def run(
    provider: Provider,
    settings: Settings,
    root: Path,
    now: datetime | None = None,
    start: date | None = None,
    end: date | None = None,
    refresh: bool = False,
    archives_only: bool = False,
) -> dict:
    daily_update = start is None and end is None and not refresh and not archives_only
    frozen_clock = now is not None
    now = now or datetime.now(UTC)
    store = Store(root)
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DataError("Another collector is writing to this data directory") from None
        latest = latest_completed(now)
        status = {
            "attempted_at": now.isoformat(),
            "expected_trade_date": latest.isoformat(),
            "state": "running",
            "updated_dates": [],
            "error": None,
        }
        try:
            dates = store.dates()
            if dates:
                existing = store.load(dates[-1])
                # JSON serializes tuples as arrays; compare normalized policies.
                policy = json.loads(json.dumps(settings.policy()))
                if existing["source"] != provider.name or existing["policy"] != policy:
                    raise DataError("Provider or universe policy differs from stored history")
            target_end = end or latest
            if target_end > latest:
                raise DataError("Requested end date has not completed its regular session")
            target_start = start or target_end
            if target_start > target_end:
                raise DataError("Start date must be on or before end date")
            targets = list(sessions(target_start, target_end))
            status["unrecoverable_dates"] = []
            for day in targets:
                update_latest = daily_update and day == latest
                if day in dates and not refresh and not update_latest:
                    continue
                if (
                    getattr(provider, "latest_only", False)
                    and (day != latest or archives_only)
                    and not (root / "bundles" / f"{day}.json").exists()
                ):
                    status["unrecoverable_dates"].append(str(day))
                    continue
                if update_latest and hasattr(provider, "refresh_latest"):
                    provider.refresh_latest(str(day))
                snapshot, raw = collect_day(
                    provider, settings, store, day, now, refresh or update_latest
                )
                if not frozen_clock:
                    snapshot["collected_at"] = datetime.now(UTC).isoformat()
                if store.save(snapshot, raw):
                    status["updated_dates"].append(day.isoformat())
                # Successful raw responses are preserved inside the revision.
                shutil.rmtree(root / "pending" / day.isoformat(), ignore_errors=True)
            status["state"] = "ok" if status["updated_dates"] else "unchanged"
            if status["unrecoverable_dates"]:
                status["state"] = "incomplete"
        except Exception as exc:
            status["state"] = "error"
            status["error"] = (
                str(exc) if isinstance(exc, DataError) else "Unexpected collection error"
            )
            raise
        finally:
            current = store.dates()
            status["latest_trade_date"] = current[-1].isoformat() if current else None
            last = store.load(current[-1]) if current else None
            status["last_success_at"] = last["collected_at"] if last else None
            status["instrument_count"] = len(last["rankings"]) if last else 0
            status["ticker_count"] = len(last["prices"]) if last else 0
            status["coverage"] = last.get("coverage") if last else None
            status["api_requests"] = getattr(provider, "requests_made", 0)
            store.status(status)
        return status
