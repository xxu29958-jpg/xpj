package com.ticketbox.data.repository

import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiService
import com.ticketbox.security.SessionTokenStore

internal class LedgerRequestGuard(
    private val settingsStore: TicketboxSettingsStore,
    private val tokenStore: SessionTokenStore,
    private val apiProvider: ApiServiceProvider,
) {
    fun activeLedgerIdOrLegacy(): String =
        settingsStore.activeLedgerId()?.takeIf { it.isNotBlank() } ?: LEGACY_LEDGER_ID

    fun bind(
        expectedLedgerId: String? = null,
        ledgerChangedMessage: String = LEDGER_CHANGED_MESSAGE,
    ): BoundLedgerRequest {
        val ledgerId = activeLedgerIdOrLegacy()
        if (expectedLedgerId != null && expectedLedgerId != ledgerId) {
            throw RepositoryException(ledgerChangedMessage)
        }
        val serverUrl = requireNotNull(settingsStore.serverUrl()) { "账本地址未绑定" }
        val token = requireNotNull(tokenStore.getToken()?.takeIf { it.isNotBlank() }) { "账本未绑定" }
        return BoundLedgerRequest(
            service = apiProvider.temporary(serverUrl, token),
            ledgerId = ledgerId,
            currentLedgerId = ::activeLedgerIdOrLegacy,
        )
    }

    suspend fun <T> guardedCall(
        expectedLedgerId: String? = null,
        ledgerChangedMessage: String = LEDGER_CHANGED_MESSAGE,
        block: suspend BoundLedgerRequest.(ApiService) -> T,
    ): T {
        val bound = bind(
            expectedLedgerId = expectedLedgerId,
            ledgerChangedMessage = ledgerChangedMessage,
        )
        return bound.call(ledgerChangedMessage) { service ->
            bound.block(service)
        }
    }

    companion object {
        const val LEGACY_LEDGER_ID = "legacy"
        const val LEDGER_CHANGED_MESSAGE = "账本已切换，请重新操作。"
        const val UPLOAD_LEDGER_CHANGED_MESSAGE = "账本已切换，请重新选择截图上传。"
    }
}

internal class BoundLedgerRequest(
    val service: ApiService,
    val ledgerId: String,
    private val currentLedgerId: () -> String,
) {
    fun isStillActive(): Boolean = currentLedgerId() == ledgerId

    fun requireStillActive(message: String = LedgerRequestGuard.LEDGER_CHANGED_MESSAGE) {
        if (!isStillActive()) {
            throw RepositoryException(message)
        }
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
