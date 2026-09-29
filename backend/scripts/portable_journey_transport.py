"""Cloud-only transfer latency around the unmodified product ASGI application."""

import asyncio
import os
from pathlib import Path

from app.main import app as product_app

if os.environ.get("GITHUB_ACTIONS") != "true":
    raise RuntimeError("The portable download fault probe requires its isolated cloud installation")


async def app(scope, receive, send):
    gate = Path(os.environ["TICKETBOX_DATA_DIR"]) / "portable-transfer-delay"

    async def delayed_send(message):
        await send(message)
        if (scope.get("path") == "/api/exports/portable" and message["type"] == "http.response.body"
            and message.get("body") and gate.exists()):
            await asyncio.sleep(2)

    await product_app(scope, receive, delayed_send)
