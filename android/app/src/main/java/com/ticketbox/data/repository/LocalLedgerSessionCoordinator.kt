package com.ticketbox.data.repository

import com.ticketbox.data.local.ExpenseDao
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.security.LocalSessionBindingUpdate
import com.ticketbox.security.LocalSessionIdentity
import com.ticketbox.security.LocalSessionRecord
import com.ticketbox.security.LocalSessionStore
import com.ticketbox.security.LocalSessionVersion
import com.ticketbox.security.StoredSessionToken
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.util.UUID

data class LedgerSessionIdentity(
    val accountPublicId: String? = null,
    val devicePublicId: String? = null,
    val accountName: String,
    val ledgerId: String,
    val ledgerName: String,
    val deviceName: String,
    val role: String,
    val boundAt: String,
)

data class LedgerSessionSnapshot(
    val serverId: String? = null,
    val dataGeneration: String? = null,
    val serverUrl: String?,
    val sessionToken: String?,
    val activeLedgerId: String?,
    val sessionGeneration: String? = null,
    val bindingRevision: String? = null,
) {
    val version: LocalSessionVersion?
        get() = sessionGeneration?.let { generation ->
            bindingRevision?.let { revision -> LocalSessionVersion(generation, revision) }
        }

    fun hasSameLogicalBinding(other: LedgerSessionSnapshot): Boolean =
        serverId == other.serverId &&
            dataGeneration == other.dataGeneration &&
            serverUrl == other.serverUrl &&
            activeLedgerId == other.activeLedgerId &&
            version == other.version
}

enum class LocalSessionChange {
    EstablishSession,
    SelectLedger,
    RefreshProjection,
}

data class LedgerSessionTransition(
    val change: LocalSessionChange,
    val identity: LedgerSessionIdentity,
    val serverId: String? = null,
    val dataGeneration: String? = null,
    val serverUrl: String? = null,
    val sessionToken: String? = null,
    val tokenExpiresAt: String? = null,
    val tokenSoftRefreshAfter: String? = null,
    val cacheInvalidation: LedgerCacheInvalidation = LedgerCacheInvalidation.None,
    val clearAvailableLedgers: Boolean = false,
    val markUnlocked: Boolean = false,
    val completedEnrollmentAttemptId: String? = null,
)

enum class LedgerCacheInvalidation {
    None,
    TargetLedger,
    AllLedgers,
}

/** Linearization point for local session establishment and ledger selection. */
class LocalLedgerSessionCoordinator(
    private val settingsStore: TicketboxSettingsStore,
    private val sessionStore: LocalSessionStore,
    private val expenseDao: ExpenseDao,
    private val outbox: OutboxRepository? = null,
) {
    private val mutex = Mutex()

    fun currentSnapshot(): LedgerSessionSnapshot = sessionStore.currentSession().toSnapshot()

    fun isCurrent(snapshot: LedgerSessionSnapshot): Boolean =
        currentSnapshot().hasSameLogicalBinding(snapshot)

    suspend fun applyTransition(transition: LedgerSessionTransition) {
        mutex.withLock {
            check(applyTransitionLocked(transition = transition, clearOutbox = false)) {
                "The local session changed while applying a transition."
            }
        }
    }

    suspend fun applyTransitionIfCurrent(
        expectedSnapshot: LedgerSessionSnapshot,
        transition: LedgerSessionTransition,
    ): Boolean = mutex.withLock {
        if (!isCurrent(expectedSnapshot)) return@withLock false
        applyTransitionLocked(transition = transition, clearOutbox = false)
    }

    internal suspend fun clearSession() {
        mutex.withLock {
            val clear: suspend () -> Unit = {
                expenseDao.clear()
                sessionStore.clearSession()
                settingsStore.clear()
            }
            val outboxRef = outbox
            if (outboxRef == null) {
                clear()
            } else {
                outboxRef.withBindingTransition(clearExistingRows = false, block = clear)
            }
        }
    }

    internal suspend fun replaceCredentialsForDebug(serverUrl: String, sessionToken: String) {
        mutex.withLock {
            val current = sessionStore.currentSession()
                ?: error("Debug credential override requires an existing session.")
            val identity = current.identity.toLedgerSessionIdentity()
            check(
                applyTransitionLocked(
                    transition = LedgerSessionTransition(
                        change = LocalSessionChange.EstablishSession,
                        identity = identity,
                        serverId = current.serverId,
                        dataGeneration = current.dataGeneration,
                        serverUrl = canonicalServerOriginOrNull(serverUrl)
                            ?: error("Debug server origin is invalid."),
                        sessionToken = sessionToken,
                        cacheInvalidation = LedgerCacheInvalidation.AllLedgers,
                        clearAvailableLedgers = true,
                        markUnlocked = true,
                    ),
                    clearOutbox = true,
                ),
            )
        }
    }

    private suspend fun applyTransitionLocked(
        transition: LedgerSessionTransition,
        clearOutbox: Boolean,
    ): Boolean {
        val current = sessionStore.currentSession()
        validateSessionTransition(transition, current)
        val commit: suspend () -> Boolean = {
            invalidateLocalCache(transition)
            val committed = persistSession(transition, current)
            if (committed) persistSessionSideEffects(transition)
            committed
        }

        if (transition.change == LocalSessionChange.RefreshProjection || outbox == null) {
            return commit()
        }
        return outbox.withBindingTransition(
            clearExistingRows = clearOutbox,
            block = commit,
        )
    }

    private suspend fun persistSession(
        transition: LedgerSessionTransition,
        current: LocalSessionRecord?,
    ): Boolean {
        val identity = transition.identity.toLocalSessionIdentity()
        if (transition.change == LocalSessionChange.EstablishSession) {
            val serverUrl = requireNotNull(transition.serverUrl)
            require(canonicalServerOriginOrNull(serverUrl) == serverUrl) {
                "New sessions must persist a canonical server origin."
            }
            sessionStore.establishSession(
                LocalSessionRecord(
                    sessionGeneration = UUID.randomUUID().toString(),
                    bindingRevision = UUID.randomUUID().toString(),
                    serverId = transition.serverId,
                    dataGeneration = transition.dataGeneration,
                    serverUrl = serverUrl,
                    credential = transition.replacementCredential(),
                    identity = identity,
                ),
                completedEnrollmentAttemptId = transition.completedEnrollmentAttemptId,
            )
            return true
        }

        val existing = requireNotNull(current)
        return sessionStore.updateBindingIfCurrent(
            LocalSessionBindingUpdate(
                expectedVersion = existing.version,
                bindingRevision = when (transition.change) {
                    LocalSessionChange.SelectLedger -> UUID.randomUUID().toString()
                    LocalSessionChange.RefreshProjection -> existing.bindingRevision
                    LocalSessionChange.EstablishSession -> error("handled above")
                },
                serverId = transition.serverId ?: existing.serverId,
                dataGeneration = transition.dataGeneration ?: existing.dataGeneration,
                serverUrl = existing.serverUrl,
                identity = identity,
                replacementCredential = transition.sessionToken?.let {
                    transition.replacementCredential()
                },
            ),
        )
    }

    private fun LedgerSessionTransition.replacementCredential(): StoredSessionToken =
        StoredSessionToken(
            token = requireNotNull(sessionToken),
            expiresAt = tokenExpiresAt,
            softRefreshAfter = tokenSoftRefreshAfter,
        )

    private suspend fun invalidateLocalCache(transition: LedgerSessionTransition) {
        when (transition.cacheInvalidation) {
            LedgerCacheInvalidation.None -> Unit
            LedgerCacheInvalidation.TargetLedger -> {
                expenseDao.clearForLedger(transition.identity.ledgerId)
                settingsStore.clearLastConfirmedSyncAtForLedger(transition.identity.ledgerId)
            }
            LedgerCacheInvalidation.AllLedgers -> {
                expenseDao.clear()
                settingsStore.clearLedgerScopedRuntimeState()
            }
        }
    }

    private fun persistSessionSideEffects(transition: LedgerSessionTransition) {
        if (transition.clearAvailableLedgers) settingsStore.saveAvailableLedgersJson(null)
        if (transition.markUnlocked) settingsStore.markUnlocked()
    }

}

private fun validateSessionTransition(
    transition: LedgerSessionTransition,
    current: LocalSessionRecord?,
) {
    when (transition.change) {
        LocalSessionChange.EstablishSession -> validateEstablishedSession(transition)
        LocalSessionChange.SelectLedger -> validateLedgerSelection(transition, current)
        LocalSessionChange.RefreshProjection -> validateProjectionRefresh(transition, current)
    }
    validateSessionContinuity(transition, current)
}

private fun validateEstablishedSession(transition: LedgerSessionTransition) {
    requireNotNull(transition.serverUrl) { "New sessions require a server origin." }
    requireNotNull(transition.sessionToken) { "New sessions require a credential." }
    require(!transition.serverId.isNullOrBlank()) { "New sessions require a logical server identity." }
    require(!transition.dataGeneration.isNullOrBlank()) { "New sessions require a server data generation." }
    require(!transition.identity.accountPublicId.isNullOrBlank()) { "New sessions require a stable account identity." }
    require(!transition.identity.devicePublicId.isNullOrBlank()) { "New sessions require a stable device identity." }
}

private fun validateLedgerSelection(
    transition: LedgerSessionTransition,
    current: LocalSessionRecord?,
) {
    val established = requireNotNull(current) { "Ledger selection requires an established session." }
    require(!(transition.serverId ?: established.serverId).isNullOrBlank()) {
        "Ledger selection requires a logical server identity."
    }
    require(!(transition.dataGeneration ?: established.dataGeneration).isNullOrBlank()) {
        "Ledger selection requires a server data generation."
    }
}

private fun validateProjectionRefresh(
    transition: LedgerSessionTransition,
    current: LocalSessionRecord?,
) {
    val established = requireNotNull(current) { "Projection refresh requires an established session." }
    require(transition.serverUrl == null && transition.sessionToken == null) {
        "Projection refresh cannot replace the server or credential."
    }
    require(established.identity.ledgerId == transition.identity.ledgerId) {
        "Projection refresh cannot select another ledger."
    }
}

private fun validateSessionContinuity(
    transition: LedgerSessionTransition,
    current: LocalSessionRecord?,
) {
    if (current == null || transition.change == LocalSessionChange.EstablishSession) return
    require(transition.serverId == null || current.serverId == null || current.serverId == transition.serverId) {
        "Logical server identity changed."
    }
    require(
        transition.dataGeneration == null ||
            current.dataGeneration == null ||
            current.dataGeneration == transition.dataGeneration,
    ) { "Server data generation changed." }
    require(
        current.identity.accountPublicId == null ||
            current.identity.accountPublicId == transition.identity.accountPublicId,
    ) { "Authenticated account identity changed." }
    require(
        current.identity.devicePublicId == null ||
            current.identity.devicePublicId == transition.identity.devicePublicId,
    ) { "Authenticated device identity changed." }
}

private fun LocalSessionRecord?.toSnapshot(): LedgerSessionSnapshot =
    LedgerSessionSnapshot(
        serverId = this?.serverId,
        dataGeneration = this?.dataGeneration,
        serverUrl = this?.serverUrl,
        sessionToken = this?.credential?.token,
        activeLedgerId = this?.identity?.ledgerId,
        sessionGeneration = this?.sessionGeneration,
        bindingRevision = this?.bindingRevision,
    )

private fun LedgerSessionIdentity.toLocalSessionIdentity(): LocalSessionIdentity =
    LocalSessionIdentity(
        accountPublicId = accountPublicId,
        devicePublicId = devicePublicId,
        accountName = accountName,
        ledgerId = ledgerId,
        ledgerName = ledgerName,
        deviceName = deviceName,
        role = role,
        boundAt = boundAt,
    )

private fun LocalSessionIdentity.toLedgerSessionIdentity(): LedgerSessionIdentity =
    LedgerSessionIdentity(
        accountPublicId = accountPublicId,
        devicePublicId = devicePublicId,
        accountName = accountName,
        ledgerId = ledgerId,
        ledgerName = ledgerName,
        deviceName = deviceName,
        role = role,
        boundAt = boundAt,
    )
