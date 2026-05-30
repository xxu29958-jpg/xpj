"""FX fetch resilience: a transient TLS handshake drop must NOT fail the whole
daily sync (this machine intermittently terminates outbound TLS handshakes, the
same flakiness that hits Maven/gradle). The fetch retries with backoff and only
raises [FxFetchError] once retries are exhausted, so the scheduler can degrade
gracefully (keep last-known rates) and log at WARNING instead of spamming ERROR.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from urllib.error import URLError

import pytest

from app.services import fx_rate_provider as provider
from app.services.fx_rate_provider import FxFetchError, fetch_ecb_daily_rates

_SAMPLE_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"'
    ' xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">'
    "<Cube>"
    '<Cube time="2026-05-15">'
    '<Cube currency="USD" rate="1.1628"/>'
    '<Cube currency="CNY" rate="7.9194"/>'
    "</Cube>"
    "</Cube>"
    "</gesmes:Envelope>"
)

_TLS_EOF = URLError("[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol")


def _ok_response() -> MagicMock:
    resp = MagicMock()
    resp.read.return_value = _SAMPLE_XML.encode("utf-8")
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


def test_fetch_retries_then_succeeds_on_transient_tls_drop() -> None:
    attempts: list[int] = []

    def fake_urlopen(_request, timeout=None):  # noqa: ANN001 - test stub
        attempts.append(1)
        if len(attempts) < 3:
            raise _TLS_EOF
        return _ok_response()

    with (
        patch.object(provider, "urlopen", side_effect=fake_urlopen),
        patch.object(provider._time, "sleep", return_value=None),
    ):
        daily = fetch_ecb_daily_rates(url="https://example.test/eurofxref-daily.xml")

    assert len(attempts) == 3, "should retry the two TLS-EOF drops before succeeding"
    assert daily.rate_date.isoformat() == "2026-05-15"
    assert daily.rates_per_eur["USD"] > 0


def test_fetch_raises_fx_fetch_error_after_exhausting_retries() -> None:
    attempts: list[int] = []

    def always_fail(_request, timeout=None):  # noqa: ANN001 - test stub
        attempts.append(1)
        raise _TLS_EOF

    with (
        patch.object(provider, "urlopen", side_effect=always_fail),
        patch.object(provider._time, "sleep", return_value=None),
        pytest.raises(FxFetchError),
    ):
        fetch_ecb_daily_rates(url="https://example.test/eurofxref-daily.xml")

    assert len(attempts) == provider.FETCH_RETRIES, "should try exactly FETCH_RETRIES times"
