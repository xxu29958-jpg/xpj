"""FileResponse delivery owns its private original snapshot until sending ends."""

from __future__ import annotations

from email.utils import formatdate

from starlette.responses import FileResponse
from starlette.types import Receive, Scope, Send

from app.services.original_read_service import OriginalSnapshot


class OriginalFileResponse(FileResponse):
    def __init__(self, snapshot: OriginalSnapshot) -> None:
        self.snapshot = snapshot
        super().__init__(
            path=snapshot.path,
            media_type=snapshot.media_type,
            headers={
                "etag": f'"{snapshot.sha256}"',
                "last-modified": formatdate(snapshot.source_modified_at, usegmt=True),
            },
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # pathsend lets the server open the path after our call returns. This
        # short-lived file must be streamed by FileResponse before its cleanup.
        extensions = {
            key: value for key, value in scope.get("extensions", {}).items()
            if key != "http.response.pathsend"
        }
        try:
            await super().__call__({**scope, "extensions": extensions}, receive, send)
        finally:
            # BackgroundTask is skipped by malformed/unsatisfiable Range and
            # send failures; ownership ends for every outcome, including cancel.
            self.snapshot.close()
