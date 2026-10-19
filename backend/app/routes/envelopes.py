"""Thin ledger-authenticated adapters for funded purposes and their retained history."""
from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_writer_context
from app.database import get_db
from app.schemas.envelopes import EnvelopeReceipt, EnvelopeRevisionView, EnvelopeSave, EnvelopesView
from app.services.envelope_commands import save_envelopes
from app.services.envelope_query import envelope_history, envelopes_view
from app.tenants import AuthContext

router = APIRouter(prefix="/api/budget/envelopes", tags=["envelopes"])


@router.get("/history/list", response_model=list[EnvelopeRevisionView])
def get_envelope_history(before_version: int | None = Query(default=None, ge=1),
        auth: AuthContext = Depends(get_current_app_context), db: Session = Depends(get_db)) -> list[EnvelopeRevisionView]:
    return envelope_history(db, tenant_id=auth.tenant_id, actor_account_id=auth.account_id, before_version=before_version)


@router.get("/{month}", response_model=EnvelopesView)
def get_envelopes(month: str, auth: AuthContext = Depends(get_current_app_context),
                  db: Session = Depends(get_db)) -> EnvelopesView:
    return envelopes_view(db, tenant_id=auth.tenant_id, actor_account_id=auth.account_id, month=month)


@router.put("/{month}", response_model=EnvelopeReceipt)
def put_envelopes(month: str, payload: EnvelopeSave, key: str = Header(alias="Idempotency-Key"),
                  auth: AuthContext = Depends(get_current_writer_context), db: Session = Depends(get_db)) -> EnvelopeReceipt:
    return save_envelopes(db, auth=auth, month=month, payload=payload, key=key)
