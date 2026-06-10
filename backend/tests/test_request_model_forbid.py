"""Request-model strictness contract (architecture debt #2).

Every ``*Request`` schema must declare ``extra="forbid"`` so an unknown
body field fails loudly with 422 instead of being silently swallowed —
a typo'd optional field, or a stale client still sending a removed
field, should surface instead of no-op'ing. Response models stay
permissive: the server constructs them, so strictness buys nothing.

The class-name suffix is the contract: request bodies are named
``XxxRequest`` (see ``app/schemas/__init__`` facade), so the sweep below
is a ratchet — a new request model that forgets ``extra="forbid"``
fails here without anyone having to remember the rule.
"""

from __future__ import annotations

import inspect

from fastapi.testclient import TestClient
from pydantic import BaseModel

from app import schemas


def _request_models() -> list[type[BaseModel]]:
    models = []
    for name in sorted(dir(schemas)):
        if not name.endswith("Request"):
            continue
        candidate = getattr(schemas, name)
        if inspect.isclass(candidate) and issubclass(candidate, BaseModel):
            models.append(candidate)
    return models


def test_every_request_model_forbids_extra_fields() -> None:
    models = _request_models()
    # Tripwire: the facade re-exports every schema. If this sweep ever
    # collapses (rename/export regression) the ratchet would pass
    # vacuously, so pin a floor just under the real count (55 today).
    assert len(models) >= 50
    offenders = [
        model.__name__
        for model in models
        if model.model_config.get("extra") != "forbid"
    ]
    assert offenders == []


def test_pair_rejects_unknown_body_field(client: TestClient, *, identity) -> None:
    created = client.post(
        "/api/bootstrap/pairing-codes",
        headers=identity.admin_headers,
        json={"ttl_minutes": 15},
    )
    assert created.status_code == 200
    pairing_code = created.json()["pairing_code"]

    rejected = client.post(
        "/api/auth/pair",
        json={
            "pairing_code": pairing_code,
            "device_name": "小米 15 Pro",
            "platform": "android",
            "is_admin": True,  # unknown field must 422, not be ignored
        },
    )
    assert rejected.status_code == 422

    # Validation fires before the service layer, so the 422 must not
    # have consumed the single-use pairing code.
    paired = client.post(
        "/api/auth/pair",
        json={
            "pairing_code": pairing_code,
            "device_name": "小米 15 Pro",
            "platform": "android",
        },
    )
    assert paired.status_code == 200
