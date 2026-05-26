package com.ticketbox.data.repository

import android.util.Log
import com.ticketbox.BuildConfig
import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
import com.ticketbox.data.remote.dto.UploadResponseDto
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.ProtectedImage
import com.ticketbox.domain.model.mergeExpenseCategories
import kotlinx.coroutines.flow.Flow
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.toRequestBody
import java.time.Instant
import kotlin.system.measureTimeMillis

internal class ExpensePendingRepository(
    private val core: ExpenseRepositoryCore,
) : PendingReviewActions {
    override fun canModifyLedger(): Boolean = core.canModifyLedger()

    override fun observeActiveLedgerId(): Flow<String?> = core.observeActiveLedgerId()

    override fun currentActiveLedgerId(): String? = core.currentActiveLedgerId()

    override suspend fun fetchPending(): Result<List<Expense>> = core.errorHandler.safeCall {
        core.ledgerRequestGuard.guardedCall { api ->
            api.pendingExpenses().map { it.toDomain() }
        }
    }

    override suspend fun uploadScreenshot(
        fileName: String,
        contentType: String?,
        bytes: ByteArray,
        preparationDurationMs: Long?,
        sourceSizeBytes: Long?,
        expectedLedgerId: String?,
    ): Result<Long> = core.errorHandler.safeCall {
        require(bytes.isNotEmpty()) { "请选择一张账单截图。" }
        val bound = core.ledgerRequestGuard.bind(
            expectedLedgerId = expectedLedgerId,
            ledgerChangedMessage = LedgerRequestGuard.UPLOAD_LEDGER_CHANGED_MESSAGE,
        )
        val cleanName = fileName
            .trim()
            .ifBlank { "ticketbox-screenshot.jpg" }
            .replace(Regex("[\\\\/:*?\"<>|]"), "_")
        val mediaType = (contentType?.takeIf { it.isNotBlank() } ?: "image/jpeg").toMediaTypeOrNull()
        val body = bytes.toRequestBody(mediaType)
        val filePart = MultipartBody.Part.createFormData("file", cleanName, body)
        var uploadResponse: UploadResponseDto? = null
        val networkDurationMs = measureTimeMillis {
            uploadResponse = bound.call(
                ledgerChangedMessage = LedgerRequestGuard.UPLOAD_LEDGER_CHANGED_MESSAGE,
            ) { it.uploadScreenshot(filePart, timezone = core.currentTimezoneId()) }
        }
        val response = requireNotNull(uploadResponse)
        if (BuildConfig.DEBUG) {
            Log.d(
                ExpenseRepositoryCore.NETWORK_LOG_TAG,
                buildString {
                    append("Screenshot upload timing: ")
                    append("prepare_ms=").append(preparationDurationMs ?: -1)
                    append(" network_ms=").append(networkDurationMs)
                    append(" server_ms=").append(response.durationMs ?: -1)
                    append(" source_bytes=").append(sourceSizeBytes ?: -1)
                    append(" upload_bytes=").append(response.uploadSizeBytes ?: bytes.size)
                    append(" server_breakdown=").append(response.timingMs.orEmpty())
                },
            )
        }
        if (bound.isStillActive()) {
            core.settingsStore.saveLastUploadAt(Instant.now().toString())
        }
        response.id
    }

    override suspend fun updateExpense(
        id: Long,
        draft: ExpenseDraft,
        baseline: Expense?,
    ): Result<Expense> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bind()
        val updated = core.cacheIfConfirmed(
            bound.call { it.updateExpense(id, draft.toRequest(baseline = baseline)) },
            bound.ledgerId,
        )
        updated.toDomain()
    }

    override suspend fun confirmExpense(
        id: Long,
        expectedUpdatedAt: String,
    ): Result<Expense> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bind()
        val confirmed = core.cacheIfConfirmed(
            bound.call {
                it.confirmExpense(id, ExpenseStateTokenRequest(expectedUpdatedAt))
            },
            bound.ledgerId,
        )
        confirmed.toDomain()
    }

    override suspend fun rejectExpense(
        id: Long,
        expectedUpdatedAt: String,
    ): Result<Expense> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bind()
        val rejected = bound.call {
            it.rejectExpense(id, ExpenseStateTokenRequest(expectedUpdatedAt))
        }
        rejected.toDomain()
    }

    override suspend fun markNotDuplicate(
        id: Long,
        expectedUpdatedAt: String,
    ): Result<Expense> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bind()
        val updated = core.cacheIfConfirmed(
            bound.call {
                it.markNotDuplicate(id, ExpenseStateTokenRequest(expectedUpdatedAt))
            },
            bound.ledgerId,
        )
        updated.toDomain()
    }

    override suspend fun fetchThumbnail(id: Long): Result<ProtectedImage> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bind()
        bound.call { core.readProtectedImage(it.expenseThumbnail(id)) }
    }

    override suspend fun categories(): Result<List<String>> = core.errorHandler.safeCall {
        core.ledgerRequestGuard.guardedCall { api ->
            mergeExpenseCategories(api.categories().items)
        }
    }
}
