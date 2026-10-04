"""Database-independent presentation of a failed inbox read, never an empty queue."""

from pathlib import Path
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.version import STATIC_ASSET_VERSION

_templates = Jinja2Templates(directory=Path(__file__).parent / "templates" / "web")


def inbox_read_error_response(request: Request, status_code: int, theme: str, request_id: str | None) -> HTMLResponse:
    # The failed request does not establish a ledger name, role, count or
    # connectivity result. Links return through the normal authenticated routes.
    ledger_id = request.query_params.get("ledger_id", "")
    query = "?" + urlencode({"ledger_id": ledger_id}) if ledger_id else ""
    return _templates.TemplateResponse(request=request, name="inbox_read_error.html", status_code=status_code,
        context={"ui_theme": theme, "request_id": request_id, "q": query,
                 "asset_version": STATIC_ASSET_VERSION, "_domain": "inbox", "pending_count": None})
