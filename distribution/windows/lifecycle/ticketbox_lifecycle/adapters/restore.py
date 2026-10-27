"""The bounded R1 coordinator's source and platform capabilities."""

from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Protocol

from ticketbox_lifecycle.schemas import InstallRequest, OwnerPairing


class RestoreSource(Protocol):
    digest: str
    identity: dict[str, Any]


class RestorePlatform(Protocol):
    def open_source(self, request: InstallRequest, path: Path, digest: str) -> AbstractContextManager[RestoreSource]: ...
    def extract_data(self, request: InstallRequest, source: RestoreSource) -> None: ...
    def prepare_data(self, request: InstallRequest, source: RestoreSource) -> None: ...
    def rotate_credentials(self, request: InstallRequest, source: RestoreSource) -> None: ...
    def rebind_identity(self, request: InstallRequest, source: RestoreSource, *, secret: str) -> OwnerPairing: ...
