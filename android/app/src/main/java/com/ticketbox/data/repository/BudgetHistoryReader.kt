package com.ticketbox.data.repository

import com.ticketbox.domain.model.BudgetHistoryPage
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emptyFlow

interface BudgetHistoryReader {
    fun observeActiveLedgerAccess(): Flow<LedgerAccessContext?>
    fun observeReadAccessDenials(): Flow<SnapshotAccessDenial> = emptyFlow()
    suspend fun history(binding: LogicalSessionBinding, month: String, beforeVersion: Long?): Result<ReadSnapshot<BudgetHistoryPage>>
}
