"""Source and archive capabilities for the existing bounded cold-copy operation."""

from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path
from typing import BinaryIO, Protocol

from ticketbox_lifecycle.adapters.ports import Mutex


class ColdCopySource(Protocol):
    def roots(self) -> dict[str, Path]: ...
    def identity(self) -> dict[str, object]: ...
    def require_stopped(self) -> None: ...


class ColdCopyPlatform(Protocol):
    mutex: Mutex

    def read_source(self) -> ColdCopySource: ...
    def create_archive(self, output: Path) -> AbstractContextManager[BinaryIO]: ...
    def write_archive(self, target: BinaryIO, source: ColdCopySource) -> dict[str, object]: ...
    def verify_archive(self, target: BinaryIO) -> dict[str, object]: ...
