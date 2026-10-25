from __future__ import annotations

import base64
import json

import pytest
from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.policy.connector_token import tunnel_identity


def encoded(**changes):
    value = {"a": "a" * 32, "s": base64.b64encode(b"x" * 32).decode(),
        "t": "77777777-7777-4777-8777-777777777777"}
    return base64.b64encode(json.dumps({**value, **changes}).encode()).decode()


def test_official_token_shape_and_empty_optional_endpoint_preserve_tunnel_identity():
    assert tunnel_identity(encoded()) == tunnel_identity(encoded(e="")) == "77777777-7777-4777-8777-777777777777"


@pytest.mark.parametrize("token", [
    encoded(e="https://custom.invalid"), encoded(unknown="extra"), encoded(s="short"),
    encoded(t="not-a-uuid"), encoded(a="account"), "partial", "not ascii \u2603", encoded() + "\n",
])
def test_unsupported_or_partial_input_has_only_a_fixed_nonsecret_error(token):
    with pytest.raises(LifecycleError) as caught:
        tunnel_identity(token)
    assert caught.value.code == "connector_token_invalid"
    assert token not in str(caught.value)
    assert caught.value.__suppress_context__
