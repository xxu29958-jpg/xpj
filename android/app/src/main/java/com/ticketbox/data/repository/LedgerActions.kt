package com.ticketbox.data.repository

import com.ticketbox.domain.model.CsvExport
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import kotlinx.coroutines.flow.Flow

interface LedgerActions {
    fun canModifyLedger(): Boolean
    fun lastConfirmedSyncAt(): String?
    fun observeConfirmed(): Flow<List<Expense>>
    suspend fun categories(): Result<List<String>>
    suspend fun tags(): Result<List<String>>
    suspend fun months(): Result<List<String>>
    suspend fun syncConfirmed(
        month: String? = null,
        category: String? = null,
        tag: String? = null,
    ): Result<List<Expense>>
    suspend fun exportConfirmedCsv(
        month: String? = null,
        category: String? = null,
        tag: String? = null,
    ): Result<CsvExport>
    suspend fun createManualExpense(draft: ExpenseDraft): Result<Expense>
}
