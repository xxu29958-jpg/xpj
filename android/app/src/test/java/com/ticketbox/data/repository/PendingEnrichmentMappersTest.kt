package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.BackgroundTaskDto
import com.ticketbox.data.remote.dto.UploadResponseDto
import com.ticketbox.domain.model.PendingEnrichmentOutcome
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

internal class PendingEnrichmentMappersTest {
    @Test
    fun uploadReceiptKeepsBothExpenseAndDurableTaskIdentity() {
        val receipt = uploadResponse().toPendingUploadReceipt()

        assertEquals(41L, receipt.expenseId)
        assertEquals("task-41", receipt.enrichmentTaskPublicId)
    }

    @Test
    fun enrichmentOutcomeIsProjectedFromTheExistingTaskContract() {
        val task = backgroundTask(resultSummary = mapOf("outcome" to "conflict"))
            .toPendingEnrichmentTask()

        assertEquals("completed", task.status)
        assertEquals(PendingEnrichmentOutcome.Conflict, task.outcome)
    }

    @Test
    fun anotherTaskTypeCannotMasqueradeAsExpenseEnrichment() {
        assertFailsWith<RepositoryException> {
            backgroundTask(taskType = "csv_import").toPendingEnrichmentTask()
        }
    }

    private fun uploadResponse() = UploadResponseDto(
        id = 41L,
        publicId = "expense-41",
        enrichmentTaskPublicId = "task-41",
        status = "pending",
        message = "uploaded",
    )

    private fun backgroundTask(
        taskType: String = "expense_enrichment",
        resultSummary: Map<String, Any?>? = null,
    ) = BackgroundTaskDto(
        publicId = "task-41",
        taskType = taskType,
        status = "completed",
        resultSummary = resultSummary,
        createdAt = "2026-08-29T00:00:00Z",
    )
}
