"""Authorized portable product data; export scope belongs to the snapshot service."""

from functools import partial

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session
from starlette.responses import FileResponse

from app.auth import get_current_app_principal
from app.database import get_db
from app.routes._portable_file_response import PortableFileResponse, portable_request_cancelled
from app.schemas import LedgerListResponse, LedgerResponse
from app.services.portable_export_access import list_portable_ledgers, resolve_portable_export_context
from app.services.portable_export_service import create_portable_ledger_export
from app.tenants import SessionPrincipal

router = APIRouter(prefix="/api/exports", tags=["exports"])


@router.get("/ledgers", response_model=LedgerListResponse)
def export_ledgers(principal: SessionPrincipal = Depends(get_current_app_principal),
                   db: Session = Depends(get_db)) -> LedgerListResponse:
    return LedgerListResponse(ledgers=[LedgerResponse.model_validate(row, from_attributes=True)
        for row in list_portable_ledgers(db, principal)])


@router.get("/portable", response_class=FileResponse, responses={200: {
    "description": "Authorized persisted ledger data and available originals; not an installation restore image.",
    "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}},
}})
def export_portable(request: Request, ledger_id: str | None = None,
                    principal: SessionPrincipal = Depends(get_current_app_principal),
                    db: Session = Depends(get_db),
                    x_ticketbox_ledger_id: str | None = Header(default=None, alias="X-Ticketbox-Ledger-ID"),
                    ) -> PortableFileResponse:
    auth = resolve_portable_export_context(db, principal,
        ledger_id=(ledger_id or x_ticketbox_ledger_id or "").strip() or None)
    # This read-only route has finished authentication. Return its connection
    # before the export acquires its independently revalidated snapshot.
    db.close()
    return PortableFileResponse(create_portable_ledger_export(
        db, auth=auth, cancel_requested=partial(portable_request_cancelled, request),
    ))
