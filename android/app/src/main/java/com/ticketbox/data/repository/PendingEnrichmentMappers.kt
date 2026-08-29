package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.BackgroundTaskDto
import com.ticketbox.data.remote.dto.UploadResponseDto
import com.ticketbox.domain.model.PendingEnrichmentOutcome
import com.ticketbox.domain.model.PendingEnrichmentTask
import com.ticketbox.domain.model.PendingUploadReceipt

internal fun UploadResponseDto.toPendingUploadReceipt(): PendingUploadReceipt = PendingUploadReceipt(
    expenseId = id,
    enrichmentTaskPublicId = enrichmentTaskPublicId,
)

internal fun BackgroundTaskDto.toPendingEnrichmentTask(): PendingEnrichmentTask {
    if (taskType != PENDING_EXPENSE_ENRICHMENT_TASK_TYPE) {
        throw RepositoryException("后台任务类型与本次识别不一致。")
    }
    val outcome = when (resultSummary?.get("outcome") as? String) {
        "updated" -> PendingEnrichmentOutcome.Updated
        "no_result" -> PendingEnrichmentOutcome.NoResult
        "not_pending" -> PendingEnrichmentOutcome.NotPending
        "conflict" -> PendingEnrichmentOutcome.Conflict
        else -> null
    }
    return PendingEnrichmentTask(
        status = status,
        outcome = outcome,
    )
}

private const val PENDING_EXPENSE_ENRICHMENT_TASK_TYPE = "expense_enrichment"
