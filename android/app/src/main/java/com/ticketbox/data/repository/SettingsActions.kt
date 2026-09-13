package com.ticketbox.data.repository

import com.ticketbox.domain.model.ConnectionDiagnostics
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ServerSettings
import kotlinx.coroutines.flow.Flow

data class LocalBindingInfo(
    val serverUrl: String,
    val accountName: String,
    val ledgerId: String,
    val ledgerName: String,
    val deviceName: String,
    val role: String,
    val boundAt: String,
)

interface SettingsActions {
    fun localBinding(): LocalBindingInfo?
    fun currentAccess(): LedgerAccessContext?
    fun observeAccess(): Flow<LedgerAccessContext?>
    fun lastConfirmedSyncAt(): String?
    fun lastUploadAt(): String?
    suspend fun runConnectionDiagnostics(binding: LogicalSessionBinding): Result<ConnectionDiagnostics>
    suspend fun serverSettings(): Result<ServerSettings>
    suspend fun syncConfirmed(
        month: String?,
        category: String?,
        tag: String?,
    ): Result<List<Expense>>
    suspend fun clearLocalCache()
}

class ExpenseRepositorySettingsActions(
    private val repository: ExpenseRepository,
) : SettingsActions {
    override fun localBinding(): LocalBindingInfo? = repository.localBinding()

    override fun currentAccess(): LedgerAccessContext? = repository.captureDeferredLedgerBinding()?.let {
        LedgerAccessContext(it, repository.canModifyLedger())
    }

    override fun observeAccess(): Flow<LedgerAccessContext?> = repository.observeLedgerAccess()

    override fun lastConfirmedSyncAt(): String? = repository.lastConfirmedSyncAt()

    override fun lastUploadAt(): String? = repository.lastUploadAt()

    override suspend fun runConnectionDiagnostics(binding: LogicalSessionBinding): Result<ConnectionDiagnostics> =
        repository.runConnectionDiagnostics(binding)

    override suspend fun serverSettings(): Result<ServerSettings> =
        repository.serverSettings()

    override suspend fun syncConfirmed(
        month: String?,
        category: String?,
        tag: String?,
    ): Result<List<Expense>> = repository.syncConfirmed(
        month = month,
        category = category,
        tag = tag,
    )

    override suspend fun clearLocalCache() {
        repository.clearLocalCache()
    }
}
