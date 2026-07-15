package com.ticketbox.data.repository

import com.ticketbox.domain.model.ConnectionDiagnostics
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ServerSettings

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
    fun currentLedgerRole(): String?
    fun lastConfirmedSyncAt(): String?
    fun lastUploadAt(): String?
    fun monthlyBudgetCents(): Long?
    fun saveMonthlyBudgetCents(amountCents: Long?)
    suspend fun testConnection(): Result<Unit>
    suspend fun runConnectionDiagnostics(): Result<ConnectionDiagnostics>
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

    override fun currentLedgerRole(): String? = repository.currentLedgerRole()

    override fun lastConfirmedSyncAt(): String? = repository.lastConfirmedSyncAt()

    override fun lastUploadAt(): String? = repository.lastUploadAt()

    override fun monthlyBudgetCents(): Long? = repository.monthlyBudgetCents()

    override fun saveMonthlyBudgetCents(amountCents: Long?) {
        repository.saveMonthlyBudgetCents(amountCents)
    }

    override suspend fun testConnection(): Result<Unit> =
        repository.testConnection()

    override suspend fun runConnectionDiagnostics(): Result<ConnectionDiagnostics> =
        repository.runConnectionDiagnostics()

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
