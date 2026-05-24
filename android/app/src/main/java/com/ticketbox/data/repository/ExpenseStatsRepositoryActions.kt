package com.ticketbox.data.repository

import com.ticketbox.domain.model.DataQualitySummary
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.LifestyleStats
import com.ticketbox.domain.model.MonthlyStats
import kotlinx.coroutines.flow.Flow

internal class ExpenseStatsRepositoryActions(
    private val core: ExpenseRepositoryCore,
    private val ledgerActions: LedgerActions,
) : StatsActions {
    override fun observeActiveLedgerId(): Flow<String?> = core.observeActiveLedgerId()

    override fun observeConfirmed(): Flow<List<Expense>> = core.observeConfirmed()

    override fun monthlyBudgetCents(): Long? = core.settingsStore.monthlyBudgetCents()

    override fun lastUploadAt(): String? = core.settingsStore.lastUploadAt()

    override suspend fun months(): Result<List<String>> = ledgerActions.months()

    override suspend fun tags(): Result<List<String>> = ledgerActions.tags()

    override suspend fun monthlyStats(month: String?, tag: String?): Result<MonthlyStats> = core.errorHandler.safeCall {
        core.ledgerRequestGuard.guardedCall { api ->
            api.monthlyStats(
                month = month,
                tag = tag?.trim()?.ifBlank { null },
                timezone = core.currentTimezoneId(),
            ).toDomain()
        }
    }

    override suspend fun lifestyleStats(month: String?): Result<LifestyleStats> = core.errorHandler.safeCall {
        core.ledgerRequestGuard.guardedCall { api ->
            api.lifestyleStats(month = month, timezone = core.currentTimezoneId()).toDomain()
        }
    }

    override suspend fun syncConfirmed(
        month: String?,
        category: String?,
        tag: String?,
    ): Result<List<Expense>> = ledgerActions.syncConfirmed(
        month = month,
        category = category,
        tag = tag,
    )

    override suspend fun dataQualitySummary(): Result<DataQualitySummary> = core.errorHandler.safeCall {
        core.ledgerRequestGuard.guardedCall { api ->
            api.dataQualitySummary().toDomain()
        }
    }
}
