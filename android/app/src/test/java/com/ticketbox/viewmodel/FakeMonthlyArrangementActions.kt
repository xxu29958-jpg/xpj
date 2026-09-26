package com.ticketbox.viewmodel

import com.ticketbox.data.repository.*
import com.ticketbox.data.remote.dto.*
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flowOf

/** Explicit fake for older budget consumers that read an unconfigured arrangement. */
internal class FakeMonthlyArrangementActions : MonthlyArrangementActions {
    private val drafts = mutableMapOf<Pair<LogicalSessionBinding, String>, MonthlyArrangementDraft>()
    override suspend fun arrangement(binding: LogicalSessionBinding, month: String) = Result.success(
        MonthlyArrangementRead(MonthlyArrangementResponseDto(binding.ledgerId, month, null)))
    override suspend fun arrangementHistory(binding: LogicalSessionBinding, month: String, beforeVersion: Long?) = Result.success(
        MonthlyArrangementHistoryRead(MonthlyArrangementHistoryDto(binding.ledgerId, month, emptyList(), null)))
    override suspend fun arrangementDraft(binding: LogicalSessionBinding, month: String) = drafts[binding to month]
    override suspend fun storeArrangementDraft(binding: LogicalSessionBinding, month: String, draft: MonthlyArrangementDraft?) {
        if (draft == null) drafts.remove(binding to month) else drafts[binding to month] = draft
    }
    override fun observeArrangements(binding: LogicalSessionBinding): Flow<List<PendingMonthlyArrangement>> = flowOf(emptyList())
    override fun describeArrangement(row: OutboxRow): PendingMonthlyArrangement? = error("Unexpected arrangement description")
    override suspend fun enqueueArrangement(binding: LogicalSessionBinding, month: String, request: MonthlyArrangementSaveRequest): Result<Long> = error("Unexpected arrangement save")
    override suspend fun recoverArrangement(binding: LogicalSessionBinding, pending: PendingMonthlyArrangement, drop: Boolean): Result<Unit> = error("Unexpected arrangement recovery")
}
