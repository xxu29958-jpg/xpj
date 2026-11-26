package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationDao
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.util.concurrent.atomic.AtomicLong

internal data class OutboxBindingSource(
    val current: () -> OutboxBinding,
    val changes: Flow<OutboxBinding>?,
)

internal data class OutboxLifecycleHooks(
    val onEnqueued: () -> Unit,
    val onClearAll: () -> Unit,
    val onRowsDeleted: suspend () -> Unit,
)

internal class OutboxBindingCoordinator(
    private val dao: PendingMutationDao,
    bindingSource: OutboxBindingSource,
    private val onClearBoundary: () -> Unit,
    private val onRowsDeleted: suspend (Int) -> Unit,
) {
    private val bindingProvider = bindingSource.current
    private val bindingChanges = bindingSource.changes
    private val sessionEpoch = AtomicLong(0L)
    private val dispatchLease = Mutex()
    private val bindingTransitionLease = Mutex()
    private val bindingRevision = MutableStateFlow(0L)

    fun currentSessionEpoch(): Long = sessionEpoch.get()

    fun bumpSessionEpochForTesting() {
        sessionEpoch.incrementAndGet()
    }

    suspend fun currentBinding(): OutboxBinding = withBindingLock { it }

    suspend fun <T> withDispatchLease(block: suspend () -> T): T =
        dispatchLease.withLock { block() }

    suspend fun <T> withBindingLock(block: suspend (OutboxBinding) -> T): T =
        bindingTransitionLease.withLock {
            block(canonicalBindingWithAliasesMigratedLocked(bindingProvider()))
        }

    suspend fun <T> withActiveBinding(
        boundRequest: BoundLedgerRequest,
        block: suspend (OutboxBinding) -> T,
    ): T = withBindingLock { binding ->
        boundRequest.requireStillActiveFor(binding)
        block(binding)
    }

    suspend fun <T> withBindingTransition(
        clearExistingRows: Boolean = false,
        serverAliasMigration: OutboxServerAliasMigration? = null,
        block: suspend () -> T,
    ): T {
        var notifyBoundary = false
        var removed = 0
        try {
            return dispatchLease.withLock {
                bindingTransitionLease.withLock {
                    sessionEpoch.incrementAndGet()
                    notifyBoundary = true
                    try {
                        if (clearExistingRows) {
                            removed = dao.clearAll()
                        }
                        migrateServerAliasLocked(serverAliasMigration)
                        block()
                    } finally {
                        bindingRevision.update { revision -> revision + 1 }
                    }
                }
            }
        } finally {
            if (notifyBoundary) {
                onClearBoundary()
            }
            onRowsDeleted(removed)
        }
    }

    fun bindingFlow(): Flow<OutboxBinding> {
        val invalidations = bindingChanges?.combine(bindingRevision) { _, revision ->
            revision
        } ?: bindingRevision
        return invalidations.map { currentBinding() }.distinctUntilChanged()
    }

    private suspend fun canonicalBindingWithAliasesMigratedLocked(
        binding: OutboxBinding,
    ): OutboxBinding {
        val raw = binding.trimmed()
        val canonical = raw.normalized()
        if (
            raw.serverUrl != canonical.serverUrl &&
            raw.ledgerId.isNotEmpty() &&
            raw.owner != null &&
            canonical.serverUrl.isNotEmpty()
        ) {
            dao.migrateServerUrlAlias(
                ownerKey = requireNotNull(raw.owner).storageKey,
                oldServerUrl = raw.serverUrl,
                newServerUrl = canonical.serverUrl,
                ledgerId = raw.ledgerId,
            )
        }
        return canonical
    }

    private suspend fun migrateServerAliasLocked(migration: OutboxServerAliasMigration?) {
        val target = migration ?: return
        val ownerKey = bindingProvider().owner?.storageKey ?: return
        dao.migrateServerUrlAlias(
            ownerKey = ownerKey,
            oldServerUrl = target.oldServerUrl,
            newServerUrl = target.newServerUrl,
            ledgerId = target.ledgerId,
        )
    }
}
