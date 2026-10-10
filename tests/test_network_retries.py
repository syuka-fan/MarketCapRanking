import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from curl_cffi import requests
from curl_cffi.const import CurlECode
from curl_cffi.requests.exceptions import ConnectionError, SSLError, Timeout
from yfinance.config import YfConfig

from marketcap.models import DataError, Settings
from marketcap.providers.yahoo import BudgetSession, RequestBudget, YahooProvider

URL = "https://query1.finance.yahoo.com/v1/finance/screener"


@pytest.fixture
def network(monkeypatch, settings):
    outcomes, sent, waits = [], [], []

    def request(self, method, url, *args, **kwargs):
        sent.append((method, url, kwargs))
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(requests.Session, "request", request)
    monkeypatch.setattr("marketcap.providers.yahoo.time.sleep", waits.append)
    monkeypatch.setattr("marketcap.providers.yahoo.random.uniform", lambda a, b: 0)
    session = BudgetSession(RequestBudget(settings))
    yield session, outcomes, sent, waits
    session.close()


def test_timeout_recovers_with_pacing_and_redacted_logs(network, capsys):
    session, outcomes, sent, waits = network
    outcomes.extend(
        [Timeout("secret-cookie"), Timeout("secret-crumb"), SimpleNamespace(status_code=200)]
    )
    response = session.post(URL + "?crumb=secret", data="same-body", timeout=90)
    assert response.status_code == 200
    assert len(sent) == session.budget.calls == 3
    assert session.budget.network_retries_used == 2
    assert all(call[2] == {"data": "same-body", "timeout": 30} for call in sent)
    assert 5 in waits and 15 in waits
    log = capsys.readouterr().out
    assert "Timeout" in log and "recovered" in log
    assert "secret" not in log


def test_repeated_timeout_stops_at_request_limit(network):
    session, outcomes, sent, _ = network
    outcomes.extend([Timeout("timeout") for _ in range(3)])
    with pytest.raises(DataError, match="Timeout.*3 attempts"):
        session.get(URL)
    assert len(sent) == session.budget.calls == 3


def test_global_retry_limit_is_shared_between_requests(network):
    session, outcomes, sent, _ = network
    session.budget.network_retry_limit = 1
    outcomes.extend([Timeout("timeout"), SimpleNamespace(status_code=200), Timeout("timeout")])
    session.get(URL)
    with pytest.raises(DataError, match="retry limit"):
        session.get(URL)
    assert len(sent) == 3
    assert session.budget.network_retries_used == 1


def test_request_budget_exhaustion_prevents_retry(network):
    session, outcomes, sent, waits = network
    session.budget.limit = 1
    outcomes.append(Timeout("timeout"))
    with pytest.raises(DataError, match="budget exhausted"):
        session.get(URL)
    with pytest.raises(DataError, match="budget exhausted"):
        session.get(URL)
    assert len(sent) == 1
    assert 5 not in waits


def test_429_during_retry_stops_all_following_requests(network):
    session, outcomes, sent, _ = network
    outcomes.extend([Timeout("timeout"), SimpleNamespace(status_code=429)])
    for _ in range(2):
        with pytest.raises(DataError, match="rate limit"):
            session.get(URL)
    assert len(sent) == session.budget.calls == 2


@pytest.mark.parametrize(
    "error",
    [
        SSLError("certificate"),
        ValueError("invalid"),
        ConnectionError("denied", code=CurlECode.REMOTE_ACCESS_DENIED),
    ],
)
def test_permanent_errors_are_not_retried(network, error):
    session, outcomes, sent, _ = network
    outcomes.append(error)
    with pytest.raises(type(error)):
        session.get(URL)
    assert len(sent) == 1


def test_connection_reset_is_retried(network):
    session, outcomes, sent, _ = network
    outcomes.extend(
        [ConnectionError("reset", code=CurlECode.RECV_ERROR), SimpleNamespace(status_code=200)]
    )
    session.get(URL)
    assert len(sent) == 2


def test_unapproved_post_is_not_replayed(network):
    session, outcomes, sent, _ = network
    outcomes.append(Timeout("timeout"))
    with pytest.raises(Timeout):
        session.post("https://query1.finance.yahoo.com/other")
    assert len(sent) == 1


@pytest.mark.parametrize("status", [401, 403, 500])
def test_http_errors_are_not_network_retries(network, status):
    session, outcomes, sent, _ = network
    outcomes.append(SimpleNamespace(status_code=status))
    assert session.get(URL).status_code == status
    assert len(sent) == 1


def test_middle_page_timeout_keeps_offset_and_completed_page(
    network, settings, tmp_path, monkeypatch
):
    session, outcomes, sent, _ = network
    provider = YahooProvider(settings, tmp_path)
    provider.session.close()
    provider.session = session
    provider.budget = session.budget
    outcomes.extend(
        [
            SimpleNamespace(status_code=200, payload={"total": 2, "quotes": [{"symbol": "A"}]}),
            Timeout("timeout"),
            SimpleNamespace(status_code=200, payload={"total": 2, "quotes": [{"symbol": "B"}]}),
        ]
    )

    def screen(query, **kwargs):
        return kwargs["session"].post(URL, data={"offset": kwargs["offset"]}).payload

    monkeypatch.setattr("marketcap.providers.yahoo.yf.screen", screen)
    monkeypatch.setattr(provider, "_text", lambda url: "directory")
    result = provider.fetch_universe()
    assert [call[2]["data"]["offset"] for call in sent] == [0, 1, 1]
    assert [quote["symbol"] for quote in result["quotes"]] == ["A", "B"]


def test_screen_preserves_exception_type_without_sensitive_text(settings, tmp_path, monkeypatch):
    provider = YahooProvider(settings, tmp_path)

    def fail(*args, **kwargs):
        raise ValueError("secret-token")

    monkeypatch.setattr("marketcap.providers.yahoo.yf.screen", fail)
    with pytest.raises(DataError, match="ValueError") as error:
        provider.screen(0)
    assert "secret-token" not in str(error.value)
    provider.session.close()


def test_network_settings_do_not_change_snapshot_policy(settings):
    assert (
        settings.policy()
        == replace(settings, network_retries=0, max_network_retries_per_run=0).policy()
    )


@pytest.mark.parametrize(
    "key,value",
    [
        ("network_retries", -1),
        ("network_retries", 9),
        ("network_retries", 1.5),
        ("max_network_retries_per_run", -1),
        ("max_network_retries_per_run", 181),
    ],
)
def test_invalid_retry_settings_rejected(tmp_path, key, value):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({key: value}))
    with pytest.raises(DataError, match="retry count"):
        Settings.read(path)


def test_provider_disables_library_retry_layer(settings, tmp_path):
    previous = YfConfig.network.retries
    try:
        YfConfig.network.retries = 4
        provider = YahooProvider(settings, tmp_path)
        assert YfConfig.network.retries == 0
        provider.session.close()
    finally:
        YfConfig.network.retries = previous
