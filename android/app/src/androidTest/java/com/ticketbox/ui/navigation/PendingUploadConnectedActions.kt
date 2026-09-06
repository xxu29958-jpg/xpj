package com.ticketbox.ui.navigation

import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.PendingReviewActions
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.data.repository.ScreenshotUploadRequest
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.PendingUploadReceipt
import java.lang.reflect.Proxy
import java.util.concurrent.CopyOnWriteArrayList
import kotlinx.coroutines.flow.flowOf

/** Remote responses only. Production VM owns preparation, the cursor, retry and refresh. */
internal class PendingUploadConnectedActions : PendingReviewActions by unusedPendingActions() {
    val uploadedNames = CopyOnWriteArrayList<String>()
    private val accepted = CopyOnWriteArrayList<Expense>()
    private var refusedB = false
    private val binding = LogicalSessionBinding("https://capture.test", "capture-ledger", "capture-owner", "session", "revision")

    override fun canModifyLedger() = true
    override fun observeActiveLedgerId() = flowOf(binding.ledgerId)
    override fun currentActiveLedgerId() = binding.ledgerId
    override fun currentUploadBinding() = binding
    override suspend fun categories() = Result.success(listOf("餐饮"))
    override suspend fun getCachedPending() = Result.success(emptyList<Expense>())
    override suspend fun fetchPending() = Result.success(accepted.toList())
    override suspend fun syncPending() = fetchPending()

    override suspend fun uploadScreenshot(request: ScreenshotUploadRequest): Result<PendingUploadReceipt> {
        check(request.expectedBinding == binding)
        uploadedNames += request.fileName
        if (request.fileName == "b.jpg" && !refusedB) {
            refusedB = true
            return Result.failure(RepositoryException("服务正忙", errorCode = "enrichment_capacity_full"))
        }
        val id = accepted.size.toLong() + 1
        accepted += uploadedExpense(id, request.fileName)
        return Result.success(PendingUploadReceipt(id, "task-$id"))
    }
}

private fun unusedPendingActions(): PendingReviewActions = Proxy.newProxyInstance(
    PendingReviewActions::class.java.classLoader,
    arrayOf(PendingReviewActions::class.java),
) { _, method, _ -> error("Unexpected Pending action: ${method.name}") } as PendingReviewActions

private fun uploadedExpense(id: Long, merchant: String) = Expense(
    id = id, publicId = "capture-$id", amountCents = 100L, merchant = merchant, category = "餐饮",
    note = null, source = "Android截图", imagePath = null, thumbnailPath = null, imageHash = null,
    rawText = null, confidence = null, duplicateStatus = "none", duplicateOfId = null, duplicateReason = null,
    tags = null, valueScore = null, regretScore = null, status = "pending", expenseTime = null,
    createdAt = "2026-09-06T00:00:00Z", updatedAt = "2026-09-06T00:00:00Z", rowVersion = 1L,
    confirmedAt = null, rejectedAt = null,
)
