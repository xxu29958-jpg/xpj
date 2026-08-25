from __future__ import annotations

from pathlib import Path

from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.runtime import layout
from ticketbox_lifecycle.runtime.windows_security import require_closed_data_root
from ticketbox_lifecycle.runtime.windows_security_native import (
    reject_reparse_components,
)
from ticketbox_lifecycle.schemas import InstallRequest


class WindowsFilesAdapter:
    name = "files"

    def apply(self, request: InstallRequest, step: str) -> str:
        if step != "programdata_root":
            raise LifecycleViolation("wrong_adapter", "files adapter only owns programdata_root")
        require_closed_data_root(request)
        for path in (
            Path(request.program_data_root),
            Path(request.data_root),
            layout.machine_root(request),
            Path(request.program_data_root) / "logs",
            layout.backend_logs(request),
            layout.secrets_dir(request),
            layout.originals(request),
            Path(request.data_root) / "app",
        ):
            reject_reparse_components(path)
            path.mkdir(parents=True, exist_ok=True)
        return "created"

    def verify(self, request: InstallRequest, step: str) -> None:
        if step != "programdata_root":
            raise LifecycleViolation("wrong_adapter", "files adapter only owns programdata_root")
        required = (
            Path(request.program_data_root),
            Path(request.data_root),
            layout.machine_root(request),
            layout.backend_logs(request),
            layout.secrets_dir(request),
            Path(request.data_root) / "app",
        )
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            raise LifecycleError("postcondition_missing", "ProgramData layout is incomplete")
