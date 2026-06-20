"""issue #64 W2 — protected image/binary responses must NEVER be gzip-compressed.

Audit finding (origin side): ``app/main.py`` registers ZERO compression
middleware — the origin compresses nothing. Whether *text* responses get
gzip/br is therefore entirely Cloudflare's job (it auto-compresses ``text/*`` +
``application/json`` by Content-Type and, per spec, skips already-compressed
image types). That half cannot be asserted from the repo — it needs a live
tunnel curl / the CF dashboard — so it stays a documented audit result, not
code. Default outcome per the issue: do NOT add app-side compression.

What this test pins is the one invariant that must hold no matter who adds
compression later: the auth-gated image / thumbnail ``FileResponse`` streams
(PNG / JPEG) are served RAW. Gzipping an already-compressed image is wasted CPU
and a CRIME-style side-channel surface. The request below sends
``Accept-Encoding: gzip`` on purpose, so a future naive global ``GZipMiddleware``
(which keys off the request's Accept-Encoding) would turn this test red.
"""

from __future__ import annotations

from api_contract_helpers import upload_png
from fastapi.testclient import TestClient

from tests._infra.assets import PNG_BYTES


def test_image_and_thumbnail_responses_are_never_gzip_compressed(
    client: TestClient, *, identity
) -> None:
    expense_id = upload_png(client, identity=identity)
    accept_gzip = {**identity.app_headers, "Accept-Encoding": "gzip"}

    image = client.get(f"/api/expenses/{expense_id}/image", headers=accept_gzip)
    assert image.status_code == 200
    assert "gzip" not in image.headers.get("content-encoding", "").lower()
    assert image.content == PNG_BYTES  # raw bytes, not a re-compressed stream

    thumbnail = client.get(f"/api/expenses/{expense_id}/thumbnail", headers=accept_gzip)
    assert thumbnail.status_code == 200
    assert "gzip" not in thumbnail.headers.get("content-encoding", "").lower()
    assert thumbnail.content.startswith(b"\xff\xd8")  # JPEG magic, served raw
