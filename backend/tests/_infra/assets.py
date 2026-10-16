"""Static byte resources used across tests."""

from __future__ import annotations

import base64

PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC"
)

RGBA_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


async def _deliver(response, *, method="GET", headers=(), extensions=None, fail_send=None):
    import asyncio

    messages = []

    async def send(message):
        if message["type"] == "http.response.body" and fail_send is not None:
            raise fail_send
        messages.append(message)

    async def receive():
        # Keep the client connected until sending finishes or fail_send fires.
        await asyncio.Event().wait()

    await response(
        {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
         "method": method, "headers": list(headers), "extensions": extensions or {}},
        receive, send,
    )
    return messages


def _camera_jpeg(seed=7):
    from io import BytesIO

    from PIL import Image

    pixels = bytes((index * 73 + index // 9 + seed) % 256 for index in range(37 * 29 * 3))
    image = Image.frombytes("RGB", (37, 29), pixels)
    exif = Image.Exif()
    exif[0x010F] = "PrivateCameraIdentity"
    exif[0x0112] = 6
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=88, exif=exif)
    return buffer.getvalue()
