"""Legacy API projection of the single Dataset Authority.

Android still names these fields ``server_id`` and ``data_generation``.  They
are derived projections, never independently persisted or mutated.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.services.dataset_authority_service import read_dataset_authority


@dataclass(frozen=True)
class ServerDataIdentity:
    server_id: str
    data_generation: str


def read_server_data_identity(db: Session) -> ServerDataIdentity:
    authority = read_dataset_authority(db)
    return ServerDataIdentity(
        server_id=authority.dataset_id,
        data_generation=authority.client_generation,
    )
