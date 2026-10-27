"""Desktop principal authority: serialized pairing, activation, ledger switch and recovery.

The Manager shell renders this owner; only this owner advances the existing
WinCred primary/recovery protocol. Host lifecycle authority remains external.
"""
from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime, timedelta

from backend_manager.config import ConfigError, ManagerConfig
from backend_manager.installation import _read_installation_binding
from backend_manager.product_data import (
    PendingProductSession,
    ProductDataError,
    derive_desktop_pending_token,
    new_activation_attempt,
)
from backend_manager.product_identity import ProductCredentialError, ProductSession
from backend_manager.product_recovery import RebindRecovery
from backend_manager.projection import RuntimeConfigProvider, display_runtime_error
from backend_manager.public_connectivity_provider import PublicConnectivityReader
from backend_manager.runtime import RuntimeControlError, RuntimeStatus
from backend_manager.web_bff import BridgeContext

# Attempt-level terminal answers: the ceremony cannot be replayed, so the
# provisional record must go (distinct from a mere wrong-code rejection).
_TERMINAL_ATTEMPT_ERRORS = frozenset({"pairing_attempt_expired", "pairing_attempt_closed"})

# A provisional pair attempt is only replayable while the backend's staged
# pending credential could still be live (300s TTL, plus a clock-skew margin).
# Mirrors the backend authority `backend/app/services/desktop_activation_service.py`
# constant ``DESKTOP_PENDING_TOKEN_TTL_SECONDS`` — the deadline here MUST NOT
# be shorter than that TTL, or the client could retire a still-live proof.
# Change only together; pinned by tests on both sides.
_PROVISIONAL_ATTEMPT_TTL_SECONDS = 300
_PROVISIONAL_ATTEMPT_EXPIRY_MARGIN_SECONDS = 60


def _provisional_deadline() -> str:
    return (datetime.now(UTC) + timedelta(seconds=_PROVISIONAL_ATTEMPT_TTL_SECONDS)).isoformat()


def _provisional_expired(recovery: RebindRecovery) -> bool:
    """Whether a provisional pair attempt is definitively closed server-side."""
    if recovery.activation_expires_at is None:
        # Written before provisional deadlines existed: age unprovable — clear
        # rather than wedge the installation behind an unreplayable proof.
        return True
    try:
        deadline = datetime.fromisoformat(recovery.activation_expires_at).timestamp()
    except ValueError:
        return True
    return time.time() > deadline + _PROVISIONAL_ATTEMPT_EXPIRY_MARGIN_SECONDS


def runtime_product_available(snapshot: RuntimeStatus) -> bool:
    """Runtime readiness for the BFF surface (pairing state is NOT included)."""
    return (
        snapshot.running
        and snapshot.healthy
        and snapshot.health_state == "healthy"
        and snapshot.runtime_access_state == "available"
        and snapshot.owner_state == "configured"
    )


def _recovery_from_pending(
    pending: PendingProductSession,
    *,
    superseded_session_token: str | None = None,
) -> RebindRecovery:
    """Persist the client-owned attempt proof plus staged display metadata.

    ``superseded_session_token`` is the cross-ledger credential the ceremony
    replaces: activation cannot retire it (the backend only accepts
    same-ledger predecessors), so it rides along until the post-promotion
    revoke succeeds — a retryable cleanup record, response-loss safe.
    """
    return RebindRecovery(
        activation_attempt_id=pending.activation_attempt_id,
        activation_attempt_secret=pending.activation_attempt_secret,
        account_name=pending.session.account_name,
        ledger_id=pending.session.ledger_id,
        ledger_name=pending.session.ledger_name,
        device_name=pending.session.device_name,
        role=pending.session.role,
        activation_expires_at=pending.session.expires_at,
        superseded_session_token=superseded_session_token,
    )


def _pending_from_recovery(recovery: RebindRecovery) -> PendingProductSession:
    """Rebuild the staged session from the durable proof (never a stored token)."""
    return PendingProductSession(
        activation_attempt_id=recovery.activation_attempt_id,
        activation_attempt_secret=recovery.activation_attempt_secret,
        session=ProductSession(
            session_token=derive_desktop_pending_token(
                recovery.activation_attempt_secret,
                recovery.activation_attempt_id,
            ),
            account_name=recovery.account_name,
            ledger_id=recovery.ledger_id,
            ledger_name=recovery.ledger_name,
            device_name=recovery.device_name,
            role=recovery.role,
            expires_at=recovery.activation_expires_at,
        ),
    )


class ProductSessions:
    """Own the one primary/recovery pair and serialize all principal consumers."""

    def __init__(
        self,
        provider: RuntimeConfigProvider,
        public_connectivity: PublicConnectivityReader,
        accept_action: Callable[[], None],
        *,
        product_session_pairer: Callable[..., PendingProductSession],
        product_ledger_switcher: Callable[..., PendingProductSession],
        product_session_activator: Callable[..., ProductSession],
        product_session_revoker: Callable[..., None],
        product_ledger_fetcher: Callable[..., list[dict]],
        product_session_loader: Callable[[str], ProductSession | None],
        product_session_saver: Callable[[str, ProductSession], None],
        product_session_deleter: Callable[[str], None],
        product_recovery_loader: Callable[[str], RebindRecovery | None],
        product_recovery_saver: Callable[[str, RebindRecovery], None],
        product_recovery_deleter: Callable[[str], None],
    ) -> None:
        self._provider = provider
        self._public_connectivity = public_connectivity
        self._accept_action = accept_action
        self._product_session_pairer = product_session_pairer
        self._product_ledger_switcher = product_ledger_switcher
        self._product_session_activator = product_session_activator
        self._product_session_revoker = product_session_revoker
        self._product_ledger_fetcher = product_ledger_fetcher
        self._product_session_loader = product_session_loader
        self._product_session_saver = product_session_saver
        self._product_session_deleter = product_session_deleter
        self._product_recovery_loader = product_recovery_loader
        self._product_recovery_saver = product_recovery_saver
        self._product_recovery_deleter = product_recovery_deleter
        self._product_session_lock = threading.RLock()

    def product_principal(self) -> dict:
        """Return only non-secret pairing metadata for the product UI."""

        with self._product_session_lock:
            config = self._product_config(require_available=False)
            session = self._load_product_session(config)
            session = self._reconcile_rebind_recovery(
                config,
                self._loopback_origin(config),
                session,
            )
            projection = session.public_projection() if session is not None else {"configured": False}
            recovery = self._load_rebind_recovery(config)
            if recovery is not None and not recovery.ledger_id and not _provisional_expired(recovery):
                projection["pairing_recovery"] = "original_code_required"
            return projection

    def product_bridge_context(self) -> BridgeContext:
        """Return secrets only to the in-process Manager BFF."""
        with self._product_session_lock:
            config = self._product_config(require_available=True)
            session = self._required_product_session(config)
            return BridgeContext(
                backend_origin=self._loopback_origin(config),
                app_token=session.session_token,
            )

    def note_product_bridge_auth_failure(self, status_code: int, failed_token: str) -> bool:
        """A bridged product request was rejected: retire exactly that credential.

        The BFF relays backend responses verbatim, so this hook is the only
        place a 401 from the product surface can retire the stored token.
        Deletion is conditional on the failed token still being the stored
        one: a request that raced a ledger switch may carry the already
        superseded credential — the fresh session must not be wiped with it.
        Returns True when the current credential was proven dead, including a
        fail-closed WinCred deletion failure (drives the rebind recovery page).
        """
        if status_code != 401:
            return False
        with self._product_session_lock:
            config = self._product_config(require_available=False)
            session = self._load_product_session(config)
            if session is None or not secrets.compare_digest(
                session.session_token,
                failed_token,
            ):
                return False
            with self._public_session_mutation():
                with suppress(ProductCredentialError):
                    self._delete_product_session(config)
                # The replacement just died while a superseded revoke was still
                # owed: attempt it here (best-effort) rather than letting the old
                # credential live to TTL with no client reference left. The
                # recovery record itself stays — reconcile owns its lifecycle,
                # and it may still hold an uncommitted ceremony.
                recovery = self._load_rebind_recovery(config)
                if recovery is not None and recovery.superseded_session_token:
                    self._revoke_superseded_session(
                        config,
                        self._loopback_origin(config),
                        recovery.superseded_session_token,
                    )
        return True

    def product_ledgers(self) -> list[dict]:
        """List the paired account's memberships for the manager switch UI."""

        with self._product_session_lock:
            config = self._product_config(require_available=True)
            session = self._required_product_session(config)
            try:
                rows = self._product_ledger_fetcher(
                    self._loopback_origin(config),
                    session.session_token,
                    timeout_seconds=config.health_request_timeout_seconds,
                )
            except ProductDataError as exc:
                self._clear_invalid_product_session(config, exc)
                raise
            return [
                {
                    **row,
                    "is_current": row["ledger_id"] == session.ledger_id,
                }
                for row in rows
            ]

    def pair_product_principal(self, pairing_code: str) -> dict:
        with self._product_session_lock:
            self._accept_action()
            return self._pair_product_principal(pairing_code)

    def _settle_outstanding_recovery(
        self,
        config: ManagerConfig,
        loopback_origin: str,
        current: ProductSession | None,
    ) -> None:
        """Settle a completed ceremony's owed superseded revoke — or refuse.

        A new pair/switch must never overwrite the single recovery slot until
        its derived successor is the durable primary and every owed revoke is
        settled. The proof is the only authority that prevents a predecessor
        accepted during Backend rotation grace from becoming current again.
        """
        existing = self._load_rebind_recovery(config)
        if existing is None or not existing.ledger_id:
            return
        successor = derive_desktop_pending_token(
            existing.activation_attempt_secret,
            existing.activation_attempt_id,
        )
        if current is None or not secrets.compare_digest(current.session_token, successor):
            raise ProductDataError(
                "已有桌面身份切换尚未完成；服务恢复后会先完成原切换。",
                error="product_rebind_recovery_pending",
                status_code=503,
            )
        owed = existing.superseded_session_token
        owed_is_orphaned = owed and (current is None or not secrets.compare_digest(current.session_token, owed))
        if owed_is_orphaned and not self._revoke_superseded_session(
            config,
            loopback_origin,
            owed,
        ):
            raise ProductDataError(
                "旧凭据尚未完成清理，请稍后重试。",
                error="product_cleanup_pending",
                status_code=503,
            )
        with suppress(ProductDataError):
            self._delete_rebind_recovery(config)

    def _pair_product_principal(self, pairing_code: str) -> dict:
        """Stage, activate, then atomically replace the WinCred principal."""

        config = self._product_config(require_available=True)
        loopback_origin = self._loopback_origin(config)
        current = self._load_product_session(config)
        current = self._reconcile_rebind_recovery(
            config,
            loopback_origin,
            current,
        )
        # Persist the attempt proof BEFORE the pairing code is consumed: a
        # response loss or process death after the backend commits would
        # otherwise orphan the staged credential forever (the one-time code
        # rejects any fresh attempt). A retry reuses the exact same proof.
        # But never overwrite a completed ceremony whose superseded revoke is
        # still owed: settle that duty first (same semantics as unpair —
        # transient failure refuses to start the new pair and keeps the record).
        self._settle_outstanding_recovery(config, loopback_origin, current)
        provisional = self._load_rebind_recovery(config)
        if provisional is not None and not provisional.ledger_id and _provisional_expired(provisional):
            # Past the pending TTL (plus margin), the backend receipt is
            # closed by construction — drop the proof so a regenerated
            # code can pair again instead of wedging this installation.
            with suppress(ProductDataError):
                self._delete_rebind_recovery(config)
            provisional = None
        if provisional is not None and not provisional.ledger_id:
            attempt = (
                provisional.activation_attempt_id,
                provisional.activation_attempt_secret,
            )
            attempt_is_fresh = False
        else:
            attempt = new_activation_attempt()
            attempt_is_fresh = True
            self._stage_rebind_recovery(
                config,
                RebindRecovery(
                    activation_attempt_id=attempt[0],
                    activation_attempt_secret=attempt[1],
                    activation_expires_at=_provisional_deadline(),
                ),
            )
        try:
            pending = self._product_session_pairer(
                loopback_origin,
                pairing_code,
                attempt=attempt,
                timeout_seconds=config.health_request_timeout_seconds,
            )
        except ProductDataError as exc:
            if exc.error in _TERMINAL_ATTEMPT_ERRORS:
                # The ceremony is terminally over (code TTL / closed): the proof
                # has no replay value — drop it so the next pair starts fresh
                # instead of retrying the same dead attempt forever.
                with suppress(ProductDataError):
                    self._delete_rebind_recovery(config)
            elif exc.error == "invalid_pairing_code" and attempt_is_fresh:
                # A proof minted in THIS call could never have committed, so
                # the rejected code really left nothing behind — drop it. A
                # reused provisional whose code was rejected is NOT cleared:
                # that 401 is a proof/code mismatch on a possibly committed
                # ceremony, which only the original code (or unpair/TTL)
                # resolves honestly.
                with suppress(ProductDataError):
                    self._delete_rebind_recovery(config)
            elif exc.error == "invalid_pairing_code":
                raise ProductDataError(
                    "上次绑定结果尚未确认，请用原绑定码继续。若原码已丢失，请等待几分钟，状态更新后再获取新码。",
                    error="product_pairing_original_code_required",
                    status_code=409,
                ) from exc
            raise
        if current is not None and secrets.compare_digest(
            current.session_token,
            pending.session.session_token,
        ):
            # Deliberate abandonment: the staged server credential dies by
            # TTL; nothing client-side should replay this ceremony later.
            with suppress(ProductDataError):
                self._delete_rebind_recovery(config)
            raise ProductDataError(
                "后端未轮换桌面身份，已保留原绑定。",
                error="product_identity_rotation_required",
                status_code=502,
            )
        recovery = _recovery_from_pending(
            pending,
            superseded_session_token=(
                current.session_token
                if current is not None and current.ledger_id != pending.session.ledger_id
                else None
            ),
        )
        self._stage_rebind_recovery(config, recovery)
        activated = self._activate_and_promote_rebind(
            config,
            loopback_origin,
            recovery,
            current,
        )
        return activated.public_projection()

    def unpair_product_principal(self) -> dict:
        with self._product_session_lock:
            self._accept_action()
            return self._unpair_product_principal()

    def _unpair_product_principal(self) -> dict:
        with self._public_session_mutation():
            return self._unpair_product_principal_inside_mutation()

    def _unpair_product_principal_inside_mutation(self) -> dict:
        """Revoke the backend token(s), then remove the local WinCred entries.

        Owed cleanup settles BEFORE teardown: when a superseded revoke fails
        transiently, unpair refuses to complete (the cleanup record stays
        retryable) instead of reporting success while a credential is orphaned.
        """

        config = self._product_config(require_available=False)
        loopback_origin = self._loopback_origin(config)
        session = self._load_product_session(config)
        session = self._reconcile_rebind_recovery(
            config,
            loopback_origin,
            session,
        )
        # A recovery record can outlive the primary — an in-flight ceremony
        # and/or an owed superseded revoke. Unpair only starts teardown once
        # the owed revoke is durably done; a transient failure keeps
        # everything in place for the next attempt.
        recovery = self._load_rebind_recovery(config)
        if recovery is not None:
            if recovery.superseded_session_token and not self._revoke_superseded_session(
                config,
                loopback_origin,
                recovery.superseded_session_token,
                lineage=True,
            ):
                raise ProductDataError(
                    "旧凭据尚未完成清理，请稍后重试解除绑定。",
                    error="product_cleanup_pending",
                    status_code=503,
                )
            with suppress(ProductDataError):
                self._delete_rebind_recovery(config)
        if session is not None:
            try:
                self._product_session_revoker(
                    loopback_origin,
                    session.session_token,
                    timeout_seconds=config.health_request_timeout_seconds,
                    # Unpair is teardown: take the staged and promoted
                    # replacements of this lineage down with the session.
                    scope="lineage",
                )
            except ProductDataError as exc:
                if exc.status_code != 401:
                    raise
            try:
                self._delete_product_session(config)
            except ProductCredentialError as exc:
                raise self._credential_error(exc) from exc
        return {"configured": False}

    def switch_product_principal_ledger(self, ledger_id: str) -> dict:
        with self._product_session_lock:
            self._accept_action()
            return self._switch_product_principal_ledger(ledger_id)

    def _switch_product_principal_ledger(self, ledger_id: str) -> dict:
        """Two-phase switch: stage on the target, activate, then retire the old."""

        config = self._product_config(require_available=True)
        loopback_origin = self._loopback_origin(config)
        current = self._required_product_session(config)
        if ledger_id == current.ledger_id:
            return current.public_projection()
        # A second switch must never overwrite a first switch's recovery slot
        # while its superseded revoke is still owed — settle first or refuse.
        self._settle_outstanding_recovery(config, loopback_origin, current)
        try:
            pending = self._product_ledger_switcher(
                loopback_origin,
                ledger_id,
                current.session_token,
                timeout_seconds=config.health_request_timeout_seconds,
            )
        except ProductDataError as exc:
            self._clear_invalid_product_session(config, exc)
            raise
        if secrets.compare_digest(current.session_token, pending.session.session_token):
            raise ProductDataError(
                "后端未轮换桌面身份，已保留原绑定。",
                error="product_identity_rotation_required",
                status_code=502,
            )
        recovery = _recovery_from_pending(
            pending,
            superseded_session_token=current.session_token,
        )
        self._stage_rebind_recovery(config, recovery)
        activated = self._activate_and_promote_rebind(
            config,
            loopback_origin,
            recovery,
            current,
        )
        return activated.public_projection()

    def _product_config(self, *, require_available: bool) -> ManagerConfig:
        if require_available and not self._product_available():
            raise ProductDataError("小票夹服务尚未就绪，请先在系统管理中恢复服务。")
        try:
            return self._provider.current().config
        except (ConfigError, RuntimeControlError) as exc:
            raise ProductDataError(display_runtime_error(self._provider, exc)) from exc

    def _product_available(self) -> bool:
        try:
            snapshot = self._provider.current().runtime.status()
        except (ConfigError, RuntimeControlError):
            return False
        return runtime_product_available(snapshot)

    @staticmethod
    def _loopback_origin(config: ManagerConfig) -> str:
        return f"http://127.0.0.1:{config.backend_port}"

    def _load_product_session(self, config: ManagerConfig) -> ProductSession | None:
        try:
            return self._product_session_loader(config.expected_installation_id)
        except ProductCredentialError as exc:
            raise self._credential_error(exc) from exc

    def _save_product_session(self, config: ManagerConfig, session: ProductSession) -> None:
        self._product_session_saver(config.expected_installation_id, session)

    def _delete_product_session(self, config: ManagerConfig) -> None:
        self._product_session_deleter(config.expected_installation_id)

    @contextmanager
    def _public_session_mutation(self) -> Iterator[None]:
        self._public_connectivity.begin_authority_mutation()
        try:
            yield
        finally:
            self._public_connectivity.end_authority_mutation()

    def _load_rebind_recovery(self, config: ManagerConfig) -> RebindRecovery | None:
        try:
            return self._product_recovery_loader(config.expected_installation_id)
        except ProductCredentialError as exc:
            raise self._credential_error(exc) from exc

    def _stage_rebind_recovery(
        self,
        config: ManagerConfig,
        recovery: RebindRecovery,
    ) -> None:
        try:
            self._product_recovery_saver(config.expected_installation_id, recovery)
        except ProductCredentialError as credential_error:
            raise self._credential_error(credential_error) from credential_error

    def _delete_rebind_recovery(self, config: ManagerConfig) -> None:
        try:
            self._product_recovery_deleter(config.expected_installation_id)
        except ProductCredentialError as exc:
            raise self._credential_error(exc) from exc

    def _reconcile_rebind_recovery(
        self,
        config: ManagerConfig,
        loopback_origin: str,
        current: ProductSession | None,
    ) -> ProductSession | None:
        recovery = self._load_rebind_recovery(config)
        if recovery is None:
            return current
        if not recovery.ledger_id:
            # Provisional pair attempt (persisted before the pairing code was
            # consumed): only an explicit pair() call completes it — a passive
            # status read must never spend the proof. Once the backend's
            # pending TTL has definitively lapsed, the proof is dead weight:
            # drop it so a regenerated code can pair again.
            if _provisional_expired(recovery):
                with suppress(ProductDataError):
                    self._delete_rebind_recovery(config)
            return current
        if not self._product_available():
            # The backend on the configured port is not identity-verified
            # right now (degraded, mismatched, or simply down). Replaying the
            # activation proof against whatever answers there could burn it:
            # a foreign/stale instance's 401 would be mistaken for an expired
            # attempt and the record deleted. Render the cached non-secret
            # session and retry the replay once the runtime is verified.
            return current
        derived = derive_desktop_pending_token(
            recovery.activation_attempt_secret,
            recovery.activation_attempt_id,
        )
        if current is not None and secrets.compare_digest(derived, current.session_token):
            # Primary already contains B. A retained superseded token means
            # the post-promotion revoke is still owed — retry it now; only a
            # durable cleanup (or a dead predecessor) drops the record.
            if recovery.superseded_session_token and not self._revoke_superseded_session(
                config,
                loopback_origin,
                recovery.superseded_session_token,
            ):
                return current
            # Duplicate recovery-slot cleanup failure must not make the valid
            # principal unusable; every later reconciliation retries it.
            with suppress(ProductDataError):
                self._delete_rebind_recovery(config)
            return current
        try:
            return self._activate_and_promote_rebind(
                config,
                loopback_origin,
                recovery,
                current,
            )
        except ProductDataError as exc:
            if exc.status_code == 401:
                # The staged attempt expired/was revoked before activation, and
                # prepare never displaced A. Hard gate: never revoke the token
                # that is still the live primary — when the failed ceremony's
                # superseded equals the current session, A was never displaced
                # and stays the user's identity. Only a genuinely orphaned
                # superseded (primary promoted past it, or already gone) may be
                # revoked here. A transient (non-death) revoke failure keeps
                # the record so a later reconcile retries; the record drops
                # only once the owed revoke succeeded or the token was dead.
                owed = recovery.superseded_session_token
                owed_settled = True
                if owed and (current is None or not secrets.compare_digest(current.session_token, owed)):
                    owed_settled = self._revoke_superseded_session(
                        config,
                        loopback_origin,
                        owed,
                    )
                if owed_settled:
                    with suppress(ProductDataError):
                        self._delete_rebind_recovery(config)
                return current
            raise

    def _activate_and_promote_rebind(
        self,
        config: ManagerConfig,
        loopback_origin: str,
        recovery: RebindRecovery,
        current: ProductSession | None,
    ) -> ProductSession:
        with self._public_session_mutation():
            return self._activate_and_promote_rebind_inside_mutation(
                config,
                loopback_origin,
                recovery,
                current,
            )

    def _activate_and_promote_rebind_inside_mutation(
        self,
        config: ManagerConfig,
        loopback_origin: str,
        recovery: RebindRecovery,
        current: ProductSession | None,
    ) -> ProductSession:
        # Only a same-ledger re-pair may prove the predecessor: the backend
        # binds X-Ticketbox-Previous-Session to the staged account AND ledger,
        # so a switch (cross-ledger) must never send it.
        previous = current.session_token if current is not None and current.ledger_id == recovery.ledger_id else None
        try:
            activated = self._product_session_activator(
                loopback_origin,
                _pending_from_recovery(recovery),
                previous,
                timeout_seconds=config.health_request_timeout_seconds,
            )
        except ProductDataError as exc:
            if exc.status_code == 401:
                raise
            raise ProductDataError(
                "新桌面身份仍安全保存在 Windows 凭据管理器中；恢复服务后会重放激活并完成切换。",
                error="product_rebind_recovery_pending",
                status_code=503,
            ) from exc
        expected = derive_desktop_pending_token(
            recovery.activation_attempt_secret,
            recovery.activation_attempt_id,
        )
        if not secrets.compare_digest(activated.session_token, expected):
            raise ProductDataError(
                "后端激活了未知桌面身份，恢复位已保留并停止提升。",
                error="product_identity_rotation_required",
                status_code=502,
            )
        try:
            self._save_product_session(config, activated)
        except ProductCredentialError as exc:
            raise ProductDataError(
                "新桌面身份已激活且仍保存在恢复位；Windows 凭据管理器恢复后会自动提升为主身份。",
                error="product_rebind_recovery_pending",
                status_code=503,
            ) from exc
        # Primary B is durable at this point. A cross-ledger predecessor is
        # never a valid activation proof, so it must be revoked client-side:
        # if that revoke fails we deliberately keep the recovery record as a
        # retryable cleanup marker instead of silently leaking the old token.
        if recovery.superseded_session_token and not self._revoke_superseded_session(
            config,
            loopback_origin,
            recovery.superseded_session_token,
        ):
            return activated
        # The recovery slot holds the same ceremony's proof, so cleanup is
        # best-effort and safely retryable.
        with suppress(ProductDataError):
            self._delete_rebind_recovery(config)
        return activated

    def _revoke_superseded_session(
        self,
        config: ManagerConfig,
        loopback_origin: str,
        session_token: str,
        *,
        lineage: bool = False,
    ) -> bool:
        """Retire one superseded credential. True when it is gone (revoked now
        or already dead); False when a later reconcile must retry.

        ``lineage=False`` is the ledger-switch cleanup intent: retire the
        predecessor, keep the promoted successor. ``lineage=True`` is reserved
        for teardown (unpair): the whole staged/promoted lineage goes with it.
        """
        try:
            self._product_session_revoker(
                loopback_origin,
                session_token,
                timeout_seconds=config.health_request_timeout_seconds,
                **({"scope": "lineage"} if lineage else {}),
            )
            return True
        except ProductDataError as exc:
            return exc.status_code == 401

    def _required_product_session(self, config: ManagerConfig) -> ProductSession:
        session = self._load_product_session(config)
        session = self._reconcile_rebind_recovery(
            config,
            self._loopback_origin(config),
            session,
        )
        if session is None:
            raise ProductDataError(
                "请先使用 8 位绑定码连接桌面账本。",
                error="product_principal_required",
                status_code=401,
            )
        return session

    def _clear_invalid_product_session(
        self,
        config: ManagerConfig,
        error: ProductDataError,
    ) -> None:
        if error.status_code != 401:
            return
        with self._public_session_mutation(), suppress(ProductCredentialError):
            self._delete_product_session(config)

    @staticmethod
    def _credential_error(error: ProductCredentialError) -> ProductDataError:
        return ProductDataError(
            str(error),
            error="product_credential_unavailable",
            status_code=503,
        )

    def connector_context(self) -> tuple[str, str, dict]:
        with self._product_session_lock:
            config = self._product_config(require_available=True)
            if config.runtime_mode != "installed":
                raise ProductDataError("受管公网连接需要正式 Windows 安装。")
            session = self._required_product_session(config)
            binding = _read_installation_binding()
            if binding is None or binding["install_id"] != config.expected_installation_id:
                raise ProductDataError("无法确认当前安装，请重新打开管理器。")
            return self._loopback_origin(config), session.session_token, binding

