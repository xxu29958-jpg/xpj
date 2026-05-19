package com.ticketbox.data.repository

import com.ticketbox.data.local.ExpenseDao
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.security.SessionTokenStore
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

data class LedgerSessionIdentity(
    val accountName: String,
    val ledgerId: String,
    val ledgerName: String,
    val deviceName: String,
    val role: String,
    val boundAt: String,
)

data class LedgerSessionSnapshot(
    val serverUrl: String?,
    val sessionToken: String?,
    val activeLedgerId: String?,
)

enum class LedgerCacheInvalidation {
    None,
    TargetLedger,
    AllLedgers,
}

/**
 * Single local boundary for persisted ledger-session changes.
 *
 * Identity is saved last so the active-ledger hot flow cannot expose a new
 * ledger before its local cache and sync markers have been invalidated.
 */
class LocalLedgerSessionCoordinator(
    private val settingsStore: TicketboxSettingsStore,
    private val tokenStore: SessionTokenStore,
    private val expenseDao: ExpenseDao,
) {
    private val mutex = Mutex()

    fun currentSnapshot(): LedgerSessionSnapshot =
        LedgerSessionSnapshot(
            serverUrl = currentServerUrl(),
            sessionToken = currentToken(),
            activeLedgerId = settingsStore.activeLedgerId(),
        )

    fun isCurrent(snapshot: LedgerSessionSnapshot): Boolean =
        currentServerUrl() == snapshot.serverUrl &&
            currentToken() == snapshot.sessionToken &&
            settingsStore.activeLedgerId() == snapshot.activeLedgerId

    suspend fun applyTransition(
        identity: LedgerSessionIdentity,
        serverUrl: String? = null,
        sessionToken: String? = null,
        cacheInvalidation: LedgerCacheInvalidation = LedgerCacheInvalidation.None,
        clearAvailableLedgers: Boolean = false,
        markUnlocked: Boolean = false,
    ) {
        mutex.withLock {
            applyTransitionLocked(
                identity = identity,
                serverUrl = serverUrl,
                sessionToken = sessionToken,
                cacheInvalidation = cacheInvalidation,
                clearAvailableLedgers = clearAvailableLedgers,
                markUnlocked = markUnlocked,
            )
        }
    }

    suspend fun applyTransitionIfCurrent(
        expectedSnapshot: LedgerSessionSnapshot,
        identity: LedgerSessionIdentity,
        serverUrl: String? = null,
        sessionToken: String? = null,
        cacheInvalidation: LedgerCacheInvalidation = LedgerCacheInvalidation.None,
        clearAvailableLedgers: Boolean = false,
        markUnlocked: Boolean = false,
    ): Boolean {
        return mutex.withLock {
            if (!isCurrent(expectedSnapshot)) return@withLock false
            applyTransitionLocked(
                identity = identity,
                serverUrl = serverUrl,
                sessionToken = sessionToken,
                cacheInvalidation = cacheInvalidation,
                clearAvailableLedgers = clearAvailableLedgers,
                markUnlocked = markUnlocked,
            )
            true
        }
    }

    private suspend fun applyTransitionLocked(
        identity: LedgerSessionIdentity,
        serverUrl: String?,
        sessionToken: String?,
        cacheInvalidation: LedgerCacheInvalidation,
        clearAvailableLedgers: Boolean,
        markUnlocked: Boolean,
    ) {
        serverUrl?.let(settingsStore::saveServerUrl)
        sessionToken?.let(tokenStore::saveToken)

        if (clearAvailableLedgers) {
            settingsStore.saveAvailableLedgersJson(null)
        }

        when (cacheInvalidation) {
            LedgerCacheInvalidation.None -> Unit
            LedgerCacheInvalidation.TargetLedger -> {
                expenseDao.clearForLedger(identity.ledgerId)
                settingsStore.clearLastConfirmedSyncAtForLedger(identity.ledgerId)
            }
            LedgerCacheInvalidation.AllLedgers -> {
                expenseDao.clear()
                settingsStore.clearLedgerScopedRuntimeState()
            }
        }

        settingsStore.saveIdentity(
            accountName = identity.accountName,
            ledgerId = identity.ledgerId,
            ledgerName = identity.ledgerName,
            deviceName = identity.deviceName,
            role = identity.role,
            boundAt = identity.boundAt,
        )
        if (markUnlocked) {
            settingsStore.markUnlocked()
        }
    }

    private fun currentServerUrl(): String? =
        settingsStore.serverUrl()?.trim()?.trimEnd('/')?.takeIf { it.isNotBlank() }

    private fun currentToken(): String? =
        tokenStore.getToken()?.takeIf { it.isNotBlank() }
}
