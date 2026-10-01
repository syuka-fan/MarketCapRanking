import json
from datetime import UTC, date, datetime

import pytest
from test_yahoo import bundle

from marketcap.calendar import regular_session_open
from marketcap.export import export_site
from marketcap.models import DataError
from marketcap.pipeline import run
from marketcap.providers.yahoo import YahooProvider
from marketcap.provisional import collect_provisional
from marketcap.storage import Store


def intraday_bundle():
    data = bundle()
    data["captured_at"] = "2026-09-30T15:00:00+00:00"
    for quote in data["quotes"]:
        quote.update(marketState="REGULAR", regularMarketTime=1790780340)
    return data


def test_repeated_intraday_updates_never_enter_closing_history(tmp_path, settings, monkeypatch):
    provider = YahooProvider(settings, tmp_path)
    data = intraday_bundle()
    monkeypatch.setattr(provider, "fetch_universe", lambda: data)
    now = datetime(2026, 9, 30, 15, tzinfo=UTC)
    for _ in range(3):
        assert collect_provisional(provider, now)["state"] == "provisional"
        export_site(tmp_path, tmp_path / "site")
    assert Store(tmp_path).dates() == []
    assert not (tmp_path / "bundles").exists()
    index = json.loads((tmp_path / "site/index.json").read_text())
    assert index["dates"] == ["2026-09-30"]
    assert index["closed_dates"] == index["axis_dates"] == []
    for company in index["instruments"]:
        path = tmp_path / "site/instruments" / company["history_file"]
        assert json.loads(path.read_text()) == {}
    csv = (tmp_path / "site/latest-prices.csv").read_text()
    assert "is_final_close" in csv and "False" in csv
    assert "close" not in csv.splitlines()[0].split(",")
    before = (tmp_path / "provisional.json").read_bytes()
    data["quotes"][0]["sharesOutstanding"] = None
    with pytest.raises(DataError, match="coverage"):
        collect_provisional(provider, now)
    assert (tmp_path / "provisional.json").read_bytes() == before
    assert json.loads((tmp_path / "status.json").read_text())["state"] == "error"


def test_completed_close_supersedes_provisional_without_contaminating_history(
    tmp_path, settings, now, monkeypatch
):
    provider = YahooProvider(settings, tmp_path)
    monkeypatch.setattr(provider, "fetch_universe", intraday_bundle)
    collect_provisional(provider, datetime(2026, 9, 30, 15, tzinfo=UTC))
    monkeypatch.setattr(provider, "fetch_bundle", lambda day: bundle())
    run(provider, settings, tmp_path, now=now)
    output = tmp_path / "site"
    export_site(tmp_path, output)
    index = json.loads((output / "index.json").read_text())
    assert index["provisional_date"] is None
    assert index["closed_dates"] == index["axis_dates"] == ["2026-09-30"]
    assert Store(tmp_path).dates() == [date(2026, 9, 30)]
    for company in index["instruments"]:
        assert list(json.loads((output / "instruments" / company["history_file"]).read_text())) == [
            "2026-09-30"
        ]


def test_session_detection_observes_early_close_and_holidays():
    assert regular_session_open(datetime(2026, 9, 30, 15, tzinfo=UTC))
    assert not regular_session_open(datetime(2026, 9, 30, 20, tzinfo=UTC))
    assert not regular_session_open(datetime(2026, 11, 26, 16, tzinfo=UTC))
    assert regular_session_open(datetime(2026, 11, 27, 17, tzinfo=UTC))
    assert not regular_session_open(datetime(2026, 11, 27, 18, tzinfo=UTC))
