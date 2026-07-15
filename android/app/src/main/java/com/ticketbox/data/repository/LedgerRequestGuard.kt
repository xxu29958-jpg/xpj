package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService

internal class LedgerRequestGuard(
    private val apiProvider: ApiServiceProvider,
) {
    fun activeLedgerIdOrLegacy(): String = currentSessionSnapshotOrNull()?.ledgerId
        ?: LEGACY_LEDGER_ID

    fun bind(
        expectedLedgerId: String? = null,
        ledgerChangedMessage: String = LEDGER_CHANGED_MESSAGE,
    ): BoundLedgerRequest {
        val snapshot = currentSessionSnapshotOrNull()
            ?: throw RepositoryException("登录状态已失效，请重新绑定。")
        if (expectedLedgerId != null && expectedLedgerId != snapshot.ledgerId) {
            throw RepositoryException(ledgerChangedMessage)
        }
        return bindSnapshot(snapshot)
    }

    fun captureLogicalBinding(): LogicalSessionBinding? =
        currentSessionSnapshotOrNull()?.logicalBinding

    fun bindExact(
        expectedBinding: LogicalSessionBinding,
        ledgerChangedMessage: String = LEDGER_CHANGED_MESSAGE,
    ): BoundLedgerRequest {
        val snapshot = currentSessionSnapshotOrNull()
            ?: throw RepositoryException("登录状态已失效，请重新绑定。")
        if (snapshot.logicalBinding != expectedBinding) {
            throw RepositoryException(ledgerChangedMessage)
        }
        return bindSnapshot(snapshot)
    }

    private fun bindSnapshot(snapshot: BoundSessionSnapshot): BoundLedgerRequest =
        BoundLedgerRequest(
            service = apiProvider.bound(
                serverUrl = snapshot.serverUrl,
                sessionGeneration = snapshot.sessionGeneration,
                ledgerId = snapshot.ledgerId,
            ),
            snapshot = snapshot,
            currentSnapshot = ::currentSessionSnapshotOrNull,
        )

    suspend fun <T> guardedCall(
        expectedLedgerId: String? = null,
        ledgerChangedMessage: String = LEDGER_CHANGED_MESSAGE,
        block: suspend BoundLedgerRequest.(ApiService) -> T,
    ): T {
        val bound = bind(expectedLedgerId, ledgerChangedMessage)
        return bound.call(ledgerChangedMessage) { service -> bound.block(service) }
    }

    private fun currentSessionSnapshotOrNull(): BoundSessionSnapshot? {
        val session = apiProvider.currentSession() ?: return null
        val owner = OutboxOwnerIdentity.fromOrNull(
            serverId = session.serverId,
            dataGeneration = session.dataGeneration,
            accountPublicId = session.identity.accountPublicId,
            devicePublicId = session.identity.devicePublicId,
        ) ?: return null
        return BoundSessionSnapshot(
            serverUrl = session.serverUrl,
            ledgerId = session.identity.ledgerId,
            owner = owner,
            token = session.credential.token,
            sessionGeneration = session.sessionGeneration,
            bindingRevision = session.bindingRevision,
        )
    }

    companion object {
        const val LEGACY_LEDGER_ID = "legacy"
        const val LEDGER_CHANGED_MESSAGE = "账本已切换，请重新操作。"
        const val UPLOAD_LEDGER_CHANGED_MESSAGE = "账本已切换，请重新选择截图上传。"
    }
}

internal data class BoundSessionSnapshot(
    val serverUrl: String,
    val ledgerId: String,
    val owner: OutboxOwnerIdentity,
    val token: String,
    val sessionGeneration: String,
    val bindingRevision: String,
) {
    val outboxBinding: OutboxBinding
        get() = OutboxBinding(serverUrl, ledgerId, owner)

    val logicalBinding: LogicalSessionBinding
        get() = LogicalSessionBinding(
            serverUrl = serverUrl,
            ledgerId = ledgerId,
            ownerKey = owner.storageKey,
            sessionGeneration = sessionGeneration,
            bindingRevision = bindingRevision,
        )
}

internal data class LogicalSessionBinding(
    val serverUrl: String,
    val ledgerId: String,
    val ownerKey: String,
    val sessionGeneration: String,
    val bindingRevision: String,
)

internal class BoundLedgerRequest(
    private val service: ApiService,
    private val snapshot: BoundSessionSnapshot,
    private val currentSnapshot: () -> BoundSessionSnapshot?,
) {
    val ledgerId: String
        get() = snapshot.ledgerId

    internal val outboxBinding: OutboxBinding
        get() = snapshot.outboxBinding

    fun isStillActive(): Boolean =
        currentSnapshot()?.logicalBinding == snapshot.logicalBinding

    fun requireStillActive(message: String = LedgerRequestGuard.LEDGER_CHANGED_MESSAGE) {
        if (!isStillActive()) throw RepositoryException(message)
    }

    internal fun requireStillActiveFor(
        binding: OutboxBinding,
        message: String = LedgerRequestGuard.LEDGER_CHANGED_MESSAGE,
    ) {
        if (binding.normalized() != outboxBinding || !isStillActive()) {
            throw RepositoryException(message)
        }
    }

    internal fun serviceFor(binding: OutboxBinding): ApiService {
        requireStillActiveFor(binding)
        return service
    }

    suspend fun <T> call(
        ledgerChangedMessage: String = LedgerRequestGuard.LEDGER_CHANGED_MESSAGE,
        block: suspend (ApiService) -> T,
    ): T {
        requireStillActive(ledgerChangedMessage)
        val result = block(service)
        requireStillActive(ledgerChangedMessage)
        return result
    }
}
