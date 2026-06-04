package com.ticketbox.data.repository

import com.ticketbox.domain.model.BatchApplyResult
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

    /**
     * ADR-0042 Slice C: apply a single field edit (category XOR tags — at least
     * one non-null) to a set of already-confirmed [expenses] by fanning out into
     * one offline-aware ``PatchExpense`` per expense. Reuses the outbox +
     * keep-mine machinery, so a stale row 409s / queues independently of its
     * siblings (partial success, reported via [BatchApplyResult]). Each expense
     * carries its own ``rowVersion`` token — the caller holds them from the
     * synced confirmed list.
     */
    suspend fun applyConfirmedBatch(
        expenses: List<Expense>,
        category: String? = null,
        tags: String? = null,
    ): Result<BatchApplyResult>
}
