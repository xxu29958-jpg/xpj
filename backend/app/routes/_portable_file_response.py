"""Sensitive request-owned archive delivery, using the original response lifecycle."""

from anyio import from_thread
from fastapi import Request
from starlette.responses import FileResponse
from starlette.types import Receive, Scope, Send

from app.services.portable_export_archive import PortableArchive


def portable_request_cancelled(request: Request) -> bool:
    """Poll the route's ASGI receive channel from its AnyIO worker thread."""
    return from_thread.run(request.is_disconnected)


class PortableFileResponse(FileResponse):
    def __init__(self, archive: PortableArchive) -> None:
        self.archive = archive
        super().__init__(path=archive.path, media_type="application/zip", filename="ticketbox-portable.zip",
                         headers={"Cache-Control": "no-store"})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # As with OriginalFileResponse, the server must not reopen a path after
        # this request has released it. FileResponse retains Range/HEAD handling.
        extensions = {key: value for key, value in scope.get("extensions", {}).items()
                      if key != "http.response.pathsend"}
        try:
            await super().__call__({**scope, "extensions": extensions}, receive, send)
        finally:
            self.archive.close()
