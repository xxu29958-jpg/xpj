package com.ticketbox.data.repository

import com.ticketbox.domain.model.BudgetHistoryPage
import kotlinx.coroutines.flow.Flow

interface BudgetHistoryReader {
    fun observeActiveLedgerAccess(): Flow<LedgerAccessContext?>
    suspend fun history(binding: LogicalSessionBinding, month: String, beforeVersion: Long?): Result<BudgetHistoryPage>
}
