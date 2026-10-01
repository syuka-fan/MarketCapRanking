import csv
import json
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from marketcap.export import export_site
from marketcap.identity import identify
from marketcap.models import DataError
from marketcap.pipeline import run
from marketcap.ranking import rank_companies
from marketcap.storage import Store


def test_multiple_tickers_are_one_company_and_after_hours_is_ignored(
    tmp_path, provider, settings, now
):
    run(provider, settings, tmp_path, now=now)
    store = Store(tmp_path)
    snapshot = store.load(date(2026, 9, 30))
    assert len(snapshot["securities"]) == len(snapshot["prices"]) == 3
    assert len(snapshot["rankings"]) == 2
    alpha = next(r for r in snapshot["rankings"] if r["company_id"] == "cik:0000000001")
    assert alpha["canonical_ticker"] == "ALPHA.A"
    assert Decimal(alpha["market_cap_usd"]) == 1000  # Not A+B caps and not afterHours.
    price_file = next((tmp_path / "snapshots").glob("*/revisions/*/prices.csv"))
    with price_file.open() as stream:
        reader = csv.DictReader(stream)
        assert reader.fieldnames[:3] == ["company_name", "ticker", "close"]
        assert {r["trade_date"] for r in reader} == {"2026-09-30"}


def test_repeat_is_noop_and_refresh_keeps_audited_revisions(tmp_path, provider, settings, now):
    run(provider, settings, tmp_path, now=now)
    count = len(provider.calls)
    assert run(provider, settings, tmp_path, now=now)["state"] == "unchanged"
    assert len(provider.calls) == count
    assert run(provider, settings, tmp_path, now=now, refresh=True)["state"] == "unchanged"
    provider.price_offset = 1
    run(provider, settings, tmp_path, now=now, refresh=True)
    assert len(list((tmp_path / "snapshots/2026-09-30/revisions").iterdir())) == 2


@pytest.mark.parametrize("failure", ["bad_date", "bad_shares"])
def test_failed_refresh_preserves_valid_snapshot(tmp_path, provider, settings, now, failure):
    run(provider, settings, tmp_path, now=now)
    before = Store(tmp_path).load(date(2026, 9, 30))
    setattr(provider, failure, True)
    with pytest.raises(DataError):
        run(provider, settings, tmp_path, now=now, refresh=True)
    assert Store(tmp_path).load(date(2026, 9, 30)) == before
    status = json.loads((tmp_path / "status.json").read_text())
    assert status["state"] == "error"
    assert status["latest_trade_date"] == "2026-09-30"


def test_detect_and_recover_internal_gaps(tmp_path, provider, settings, now):
    run(provider, settings, tmp_path, now=now, start=date(2026, 9, 28), end=date(2026, 9, 28))
    run(provider, settings, tmp_path, now=now, start=date(2026, 9, 30))
    assert Store(tmp_path).dates() == [date(2026, 9, 28), date(2026, 9, 30)]
    status = run(provider, settings, tmp_path, now=now)
    assert status["updated_dates"] == ["2026-09-29"]


def test_holiday_does_not_create_a_snapshot(tmp_path, provider, settings, now):
    run(provider, settings, tmp_path, now=now, start=date(2026, 7, 3), end=date(2026, 7, 3))
    assert not Store(tmp_path).dates()
    assert not provider.calls


def test_future_session_is_rejected(tmp_path, provider, settings, now):
    with pytest.raises(DataError, match="not completed"):
        run(provider, settings, tmp_path, now=now, end=date(2026, 10, 1))
    assert not provider.calls


def test_identity_survives_rename_and_missing_identity_is_rejected(provider, settings):
    before = identify(provider.tickers("2026-09-29"), settings)
    provider.renamed = True
    after = identify(provider.tickers("2026-09-30"), settings)
    renamed = next(s for s in after if s.security_id == before[0].security_id)
    assert before[0].company_id == renamed.company_id
    assert before[0].ticker != renamed.ticker
    rows = provider.tickers("2026-09-30")
    rows[0].pop("cik")
    with pytest.raises(DataError, match="identity"):
        identify(rows, settings)


def test_ties_use_competition_rank():
    result = rank_companies(
        [
            {"company_id": key, "market_cap_usd": cap}
            for key, cap in [("a", "100"), ("b", "90"), ("c", "90"), ("d", "80")]
        ]
    )
    assert [r["rank"] for r in result] == [1, 2, 2, 4]


def test_universe_drop_and_policy_changes_are_not_published(tmp_path, provider, settings, now):
    run(provider, settings, tmp_path, now=now, start=date(2026, 9, 29), end=date(2026, 9, 29))
    provider.omit_beta = True
    with pytest.raises(DataError, match="shrank"):
        run(provider, settings, tmp_path, now=now)
    assert Store(tmp_path).dates() == [date(2026, 9, 29)]
    with pytest.raises(DataError, match="policy"):
        run(provider, replace(settings, exchanges=("XNYS",)), tmp_path, now=now)


def test_export_recomputes_changes_after_backfill_and_keeps_gaps(tmp_path, provider, settings, now):
    root = tmp_path / "records"
    output = tmp_path / "site"
    run(provider, settings, root, now=now, start=date(2026, 9, 28), end=date(2026, 9, 28))
    run(provider, settings, root, now=now, start=date(2026, 9, 30))
    export_site(root, output)
    with (output / "latest-rankings.csv").open() as stream:
        exported = list(csv.DictReader(stream))
    assert len(exported) == 2
    assert [r["rank"] for r in exported] == ["1", "2"]
    index = json.loads((output / "index.json").read_text())
    assert index["axis_dates"] == ["2026-09-28", "2026-09-29", "2026-09-30"]
    day = json.loads((output / "days/2026-09-30.json").read_text())
    assert all(r["change_state"] == "gap" for r in day["rows"])
    run(provider, settings, root, now=now)
    export_site(root, output)
    day = json.loads((output / "days/2026-09-30.json").read_text())
    assert all(r["rank_change"] == 0 for r in day["rows"])


def test_export_empty_is_valid(tmp_path):
    export_site(tmp_path / "empty", tmp_path / "site")
    index = json.loads((tmp_path / "site/index.json").read_text())
    assert index["dates"] == []
    assert index["is_demo"] is False


def test_no_current_shares_are_reused_for_history(tmp_path, provider, settings, now):
    original_details = provider.details
    original_close = provider.close

    def split_details(ticker, day):
        result = original_details(ticker, day)
        result["weighted_shares_outstanding"] = 200 if day == "2026-09-30" else 100
        return result

    def split_close(ticker, day):
        result = original_close(ticker, day)
        if day == "2026-09-30":
            result["close"] /= 2
        return result

    provider.details = split_details
    provider.close = split_close
    run(provider, settings, tmp_path, now=now, start=date(2026, 9, 29))
    store = Store(tmp_path)
    caps = [[r["market_cap_usd"] for r in store.load(d)["rankings"]] for d in store.dates()]
    assert caps[0] == caps[1]


def test_invalid_response_is_not_cached_forever(tmp_path, provider, settings, now):
    provider.bad_date = True
    with pytest.raises(DataError):
        run(provider, settings, tmp_path, now=now)
    provider.bad_date = False
    assert run(provider, settings, tmp_path, now=now)["state"] == "ok"


def test_older_refresh_reuses_immutable_revision(tmp_path, provider, settings, now):
    run(provider, settings, tmp_path, now=now)
    original = next((tmp_path / "snapshots").glob("*/revisions/*/snapshot.json"))
    original_bytes = original.read_bytes()
    provider.price_offset = 1
    run(provider, settings, tmp_path, now=now, refresh=True)
    provider.price_offset = 0
    from datetime import timedelta

    run(provider, settings, tmp_path, now=now + timedelta(hours=1), refresh=True)
    assert original.read_bytes() == original_bytes
