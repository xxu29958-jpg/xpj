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
    /**
     * Optional outbox boundary hook. Session transitions pause
     * dispatch before credentials are written; binding-scoped rows
     * then prevent old ledger/server mutations from replaying under
     * the new session. ``null`` keeps tests and older construction
     * sites at the original behaviour.
     */
    private val outbox: OutboxRepository? = null,
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
        tokenExpiresAt: String? = null,
        tokenSoftRefreshAfter: String? = null,
        cacheInvalidation: LedgerCacheInvalidation = LedgerCacheInvalidation.None,
        clearAvailableLedgers: Boolean = false,
        markUnlocked: Boolean = false,
    ) {
        mutex.withLock {
            applyTransitionLocked(
                identity = identity,
                serverUrl = serverUrl,
                sessionToken = sessionToken,
                tokenExpiresAt = tokenExpiresAt,
                tokenSoftRefreshAfter = tokenSoftRefreshAfter,
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
        tokenExpiresAt: String? = null,
        tokenSoftRefreshAfter: String? = null,
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
                tokenExpiresAt = tokenExpiresAt,
                tokenSoftRefreshAfter = tokenSoftRefreshAfter,
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
        tokenExpiresAt: String?,
        tokenSoftRefreshAfter: String?,
        cacheInvalidation: LedgerCacheInvalidation,
        clearAvailableLedgers: Boolean,
        markUnlocked: Boolean,
    ) {
        if (cacheInvalidation != LedgerCacheInvalidation.None && outbox != null) {
            outbox.withBindingTransition {
                serverUrl?.let(settingsStore::saveServerUrl)
                sessionToken?.let { token ->
                    tokenStore.saveToken(
                        token = token,
                        expiresAt = tokenExpiresAt,
                        softRefreshAfter = tokenSoftRefreshAfter,
                    )
                }

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
            return
        }

        // The outbox dispatch boundary MUST be paused BEFORE any
        // credential change.
        //
        // The drain engine's [OutboxDrainEngine] post-claim epoch
        // check catches "epoch already bumped" before dispatch. But
        // if we write serverUrl/sessionToken FIRST and only bump
        // the epoch later via outbox.pauseForBindingTransition(),
        // there's a window
        // where a concurrent drain has:
        //   - passed the post-claim epoch check (epoch still old)
        //   - reads apiProvider() inside dispatch → already sees
        //     the NEW serverUrl / sessionToken
        //   - sends the OLD row under the NEW session
        //
        // Order: pause FIRST: the epoch bumps before any new
        // credential is visible. The drain either:
        //   - hasn't captured epoch yet → captures the new value and
        //     drains only rows for the new binding
        //   - has captured old epoch but not yet claimed any row →
        //     post-claim check fires on next iteration, aborts
        //   - has captured old epoch AND already passed the
        //     post-claim check → it WILL dispatch, but apiProvider
        //     still resolves the OLD credentials (we haven't
        //     written the new ones yet); the request goes under
        //     the OLD session, which is the safer failure mode
        //     ("old-session in-flight" vs "wrong-session replay").
        //
        // Old-session in-flight at the boundary moment is a real
        // residual, but binding-scoped drain reads prevent queued
        // old rows from replaying after the switch.
        if (cacheInvalidation != LedgerCacheInvalidation.None) {
            outbox?.pauseForBindingTransition()
        }

        serverUrl?.let(settingsStore::saveServerUrl)
        sessionToken?.let { token ->
            tokenStore.saveToken(
                token = token,
                expiresAt = tokenExpiresAt,
                softRefreshAfter = tokenSoftRefreshAfter,
            )
        }

        if (clearAvailableLedgers) {
            settingsStore.saveAvailableLedgersJson(null)
        }

        when (cacheInvalidation) {
            LedgerCacheInvalidation.None -> Unit
            LedgerCacheInvalidation.TargetLedger -> {
                expenseDao.clearForLedger(identity.ledgerId)
                settingsStore.clearLastConfirmedSyncAtForLedger(identity.ledgerId)
                // outbox.pauseForBindingTransition() already ran
                // above; cache invalidation below is just the local
                // expense rows.
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
