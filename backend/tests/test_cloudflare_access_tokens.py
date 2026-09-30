"""Exercise the actual JWKS parser and verifier used at the public Web boundary."""
import base64
import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.services import cloudflare_access_service as access

TEAM = "https://family.cloudflareaccess.com"


def test_access_verifies_real_jwks_and_rejects_invalid_signature_claims_and_key(monkeypatch):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    client = jwt.PyJWKClient(f"{TEAM}/cdn-cgi/access/certs")
    monkeypatch.setattr(client, "fetch_data", lambda: {"keys": [{**public, "kid": "active", "use": "sig"}]})
    monkeypatch.setattr(access, "_jwk_client", lambda _: client)
    claims = {"sub": "test-account", "aud": "access-aud", "iss": TEAM, "exp": int(time.time()) + 60}

    def verify(token):
        return access.verify_cloudflare_access_jwt(token, team_domain=TEAM, audience="access-aud")

    def encode(payload, key=private, kid="active"):
        return jwt.encode(payload, key, algorithm="RS256", headers={"kid": kid})

    assert verify(encode(claims))["sub"] == "test-account"
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    invalid = [encode(claims, other_key), encode(claims, kid="retired"),
        *(encode({**claims, field: value}) for field, value in [("aud", "other"), ("iss", "https://other.example"), ("exp", 1)])]
    for token in invalid:
        with pytest.raises(access.CloudflareAccessVerificationError):
            verify(token)


def test_untrusted_deep_payload_fails_as_decode_error_before_jwks_fetch(monkeypatch):
    def segment(raw):
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    token = ".".join([segment(b'{"alg":"RS256","kid":"active"}'), segment(b'[' * 2000 + b'0' + b']' * 2000), "AA"])
    client = jwt.PyJWKClient(f"{TEAM}/cdn-cgi/access/certs")
    monkeypatch.setattr(client, "fetch_data", lambda: pytest.fail("Invalid payload must not fetch keys"))
    monkeypatch.setattr(access, "_jwk_client", lambda _: client)
    with pytest.raises(access.CloudflareAccessVerificationError) as failure:
        access.verify_cloudflare_access_jwt(token, team_domain=TEAM, audience="access-aud")
    assert isinstance(failure.value.__cause__, jwt.DecodeError)
