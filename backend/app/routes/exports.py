"""Authorized portable product data; export scope belongs to the snapshot service."""

from functools import partial

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from starlette.responses import FileResponse

from app.auth import get_current_app_context
from app.database import get_db
from app.routes._portable_file_response import PortableFileResponse, portable_request_cancelled
from app.services.portable_export_service import create_portable_ledger_export
from app.tenants import AuthContext

router = APIRouter(prefix="/api/exports", tags=["exports"])


@router.get("/portable", response_class=FileResponse, responses={200: {
    "description": "Authorized persisted ledger data and available originals; not an installation restore image.",
    "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}},
}})
def export_portable(request: Request, auth: AuthContext = Depends(get_current_app_context),
                    db: Session = Depends(get_db)) -> PortableFileResponse:
    # This read-only route has finished authentication. Return its connection
    # before the export acquires its independently revalidated snapshot.
    db.close()
    return PortableFileResponse(create_portable_ledger_export(
        db, auth=auth, cancel_requested=partial(portable_request_cancelled, request),
    ))
