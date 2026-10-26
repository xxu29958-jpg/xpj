"""Exact connector metadata and secret authority, separate from database secrets."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from uuid import UUID

from ticketbox_lifecycle.connector_schema import ConnectorState, parse_state
from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.policy.connector_token import tunnel_identity
from ticketbox_lifecycle.runtime import windows_security_native as native
from ticketbox_lifecycle.runtime.command import SubprocessCommandRunner
from ticketbox_lifecycle.runtime.filesystem_stores import _write_temp_json
from ticketbox_lifecycle.runtime.windows_cold_file import create_private_archive
from ticketbox_lifecycle.runtime.windows_file_security import WindowsFileSecurity, file_dacl_sddl

# This SID is stable for the fixed service name on every Windows host. It is
# read back through LookupAccountName after creation before allowing a start.
CONNECTOR_SID = "S-1-5-80-3024674666-645836238-1311512546-1624255824-3956361124"


class WindowsConnectorFiles:
    def __init__(self, machine_root: Path, backend_sid: str) -> None:
        self.root = machine_root / "connectors" / "cloudflare"
        self.secrets = self.root / "secrets"
        self.backend_sid = backend_sid
        self.runner = SubprocessCommandRunner()
        self.security = WindowsFileSecurity()

    def prepare_roots(self) -> None:
        for path in (self.root.parent, self.root):
            native.create_protected_directory(path, backend_reader_sid=self.backend_sid,
                interactive_reader_sid=CONNECTOR_SID, code="connector_directory_untrusted")

    def read(self) -> ConnectorState | None:
        path = self.root / "state.json"
        native.reject_reparse_components(path)
        if not path.exists():
            return None
        self._require_file(path, (self.backend_sid,))
        with path.open("rb") as stream:
            raw = stream.read(8193)
        self._require_file(path, (self.backend_sid,))
        if len(raw) > 8192:
            raise LifecycleError("connector_state_invalid", "connector metadata exceeds its limit")
        try:
            return parse_state(json.loads(raw))
        except (ValueError, UnicodeError):
            raise LifecycleError("connector_state_invalid", "connector metadata is unreadable") from None

    def publish(self, state: ConnectorState) -> None:
        parse_state(asdict(state))
        self.prepare_roots()
        path = self.root / "state.json"
        native.reject_reparse_components(path)
        temporary = _write_temp_json(path, asdict(state))
        try:
            self.security.protect_file(self.runner, temporary, reader_sids=(self.backend_sid,), code="connector_state_security")
            self._require_file(temporary, (self.backend_sid,))
            os.replace(temporary, path)
            if self.read() != state:
                raise LifecycleError("connector_state_changed", "connector state failed exact readback")
        finally:
            if temporary.exists():
                temporary.unlink()

    def credential_path(self, generation: int) -> Path:
        if type(generation) is not int or not 0 < generation < 2**53:
            raise LifecycleError("connector_generation_invalid", "credential generation is invalid")
        return self.secrets / f"credential-g{generation}.token"

    def _candidate_path(self, generation: int, operation_id: str) -> Path:
        if str(UUID(operation_id)) != operation_id:
            raise LifecycleError("connector_identity_invalid", "candidate operation identity is invalid")
        return self.credential_path(generation).with_suffix(f".{operation_id}.pending")

    def credential_identity(self, generation: int, operation_id: str, token: str | None = None) -> str:
        if token is not None:
            tunnel_identity(token)
        path = self.credential_path(generation)
        native.reject_reparse_components(path)
        if path.exists():
            return self._credential_identity(path, token, candidate=False)
        candidate = self._candidate_path(generation, operation_id)
        native.reject_reparse_components(candidate)
        if candidate.exists():
            try:
                return self._credential_identity(candidate, token, candidate=True)
            except LifecycleError as exc:
                # Only an incomplete write owned by this exact operation may
                # be replaced, and only after new native input is available.
                if exc.code != "connector_token_invalid" or token is None:
                    raise
        if token is None:
            raise LifecycleError("connector_credential_missing", "native credential input is needed to continue this operation")
        return tunnel_identity(token)

    def _credential_identity(self, path: Path, token: str | None, *, candidate: bool) -> str:
        self._require_credential_file(path, candidate=candidate)
        with path.open("rb") as stream:
            raw = stream.read(16385)
        self._require_credential_file(path, candidate=candidate)
        try:
            identity = tunnel_identity(raw.decode("ascii"))
        except UnicodeError:
            raise LifecycleError("connector_token_invalid", "stored credential is incomplete") from None
        if token is not None and raw != token.encode("ascii"):
            raise LifecycleViolation("connector_candidate_changed", "this operation already owns a different candidate credential")
        return identity

    def prepare_credential(self, generation: int, operation_id: str, token: str | None) -> None:
        self.credential_identity(generation, operation_id, token)
        self.prepare_roots()
        native.create_protected_directory(self.secrets, backend_reader_sid=CONNECTOR_SID,
            interactive_reader_sid=None, code="connector_secret_directory_untrusted")
        path = self.credential_path(generation)
        if path.exists():
            return
        candidate = self._candidate_path(generation, operation_id)
        if candidate.exists():
            try:
                self._credential_identity(candidate, token, candidate=True)
            except LifecycleError as exc:
                if exc.code != "connector_token_invalid" or token is None:
                    raise
                candidate.unlink()
        # Creation-time Admin/SYSTEM DACL precedes every secret byte. The
        # service path is published only after a durable write and ACL readback.
        if not candidate.exists():
            if token is None:
                raise LifecycleError("connector_credential_missing", "native credential input is needed")
            try:
                with create_private_archive(candidate) as stream:
                    stream.write(token.encode("ascii"))
                    stream.flush()
                    os.fsync(stream.fileno())
            except LifecycleError:
                raise LifecycleError("connector_secret_security", "cannot create a protected credential candidate") from None
        self.security.protect_file(self.runner, candidate, reader_sids=(CONNECTOR_SID,), code="connector_secret_security")
        self._require_file(candidate, (CONNECTOR_SID,))
        os.replace(candidate, path)
        self._require_file(path, (CONNECTOR_SID,))

    def remove_generation(self, generation: int) -> None:
        if generation == 0:
            return
        path = self.credential_path(generation)
        native.reject_reparse_components(path)
        if path.exists():
            self._require_file(path, (CONNECTOR_SID,))
            path.unlink()
        if path.exists():
            raise LifecycleError("connector_secret_delete_pending", "credential cleanup has not completed")

    def remove_candidate(self, generation: int, operation_id: str) -> None:
        path = self._candidate_path(generation, operation_id)
        native.reject_reparse_components(path)
        if path.exists():
            self._require_credential_file(path, candidate=True)
            path.unlink()
        if path.exists():
            raise LifecycleError("connector_secret_delete_pending", "candidate cleanup has not completed")

    @staticmethod
    def _require_credential_file(path: Path, *, candidate: bool) -> None:
        native.reject_reparse_components(path)
        native.require_trusted_owner(path, code="connector_file_untrusted", message="connector file has an untrusted owner")
        policies = [file_dacl_sddl((CONNECTOR_SID,))]
        if candidate:
            policies.append("D:P(A;;FA;;;SY)(A;;FA;;;BA)")
        if not path.is_file() or native._object_dacl_sddl(path) not in {native._canonical_dacl_sddl(p) for p in policies}:
            raise LifecycleViolation("connector_file_untrusted", "credential permissions do not match its publication phase")

    @staticmethod
    def _require_file(path: Path, readers: tuple[str, ...]) -> None:
        native.reject_reparse_components(path)
        native.require_trusted_owner(path, code="connector_file_untrusted", message="connector file has an untrusted owner")
        if not path.is_file() or native._object_dacl_sddl(path) != native._canonical_dacl_sddl(file_dacl_sddl(readers)):
            raise LifecycleViolation("connector_file_untrusted", "connector file permissions do not match the exact reader set")
