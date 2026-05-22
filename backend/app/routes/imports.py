from __future__ import annotations

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_writer_context
from app.database import get_db
from app.schemas import (
    CsvImportApplyRequest,
    CsvImportApplyResponse,
    CsvImportBatchResponse,
    CsvImportRowsResponse,
)
from app.services.csv_import_batch_service import (
    apply_csv_import_batch,
    build_csv_import_errors_csv,
    create_csv_import_batch,
    get_csv_import_batch,
    list_csv_import_rows,
)
from app.tenants import AuthContext

router = APIRouter(prefix="/api/imports/csv", tags=["imports"])


@router.post("", response_model=CsvImportBatchResponse, status_code=201)
async def post_csv_import_batch(
    csv_file: UploadFile = File(...),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> CsvImportBatchResponse:
    batch = create_csv_import_batch(
        db,
        tenant_id=auth.tenant_id,
        file_name=csv_file.filename,
        file_obj=csv_file.file,
    )
    return CsvImportBatchResponse.model_validate(batch)


@router.get("/{public_id}", response_model=CsvImportBatchResponse)
def get_csv_import_batch_detail(
    public_id: str,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> CsvImportBatchResponse:
    batch = get_csv_import_batch(db, tenant_id=auth.tenant_id, public_id=public_id)
    return CsvImportBatchResponse.model_validate(batch)


@router.get("/{public_id}/rows", response_model=CsvImportRowsResponse)
def get_csv_import_batch_rows(
    public_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    status: str | None = None,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> CsvImportRowsResponse:
    return list_csv_import_rows(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        page=page,
        page_size=page_size,
        status=status,
    )


@router.post("/{public_id}/apply", response_model=CsvImportApplyResponse)
def post_csv_import_batch_apply(
    public_id: str,
    payload: CsvImportApplyRequest | None = None,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> CsvImportApplyResponse:
    request = payload or CsvImportApplyRequest()
    return apply_csv_import_batch(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        batch_size=request.batch_size,
    )


@router.get("/{public_id}/errors.csv")
def get_csv_import_batch_errors_csv(
    public_id: str,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> Response:
    content = "\ufeff" + build_csv_import_errors_csv(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
    )
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="ticketbox-import-errors.csv"'},
    )
