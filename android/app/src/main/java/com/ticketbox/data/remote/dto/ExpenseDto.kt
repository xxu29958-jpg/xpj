package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json

data class UploadResponseDto(
    val id: Long,
    @param:Json(name = "public_id")
    val publicId: String,
    val status: String,
    val message: String,
    @param:Json(name = "upload_size_bytes")
    val uploadSizeBytes: Long? = null,
    @param:Json(name = "duration_ms")
    val durationMs: Long? = null,
    @param:Json(name = "timing_ms")
    val timingMs: Map<String, Long>? = null,
)

data class PendingCategorySuggestionDto(
    @param:Json(name = "decision_public_id")
    val decisionPublicId: String,
    val category: String,
    val score: Double,
    @param:Json(name = "sample_size")
    val sampleSize: Int,
    @param:Json(name = "algorithm_version")
    val algorithmVersion: String,
)

data class PendingDuplicateCandidateDto(
    @param:Json(name = "decision_public_id")
    val decisionPublicId: String,
    @param:Json(name = "candidate_id")
    val candidateId: Long,
    @param:Json(name = "candidate_public_id")
    val candidatePublicId: String? = null,
    val score: Double,
    val reasons: List<String> = emptyList(),
    @param:Json(name = "algorithm_version")
    val algorithmVersion: String,
)

data class ExpenseDto(
    val id: Long,
    @param:Json(name = "public_id")
    val publicId: String? = null,
    @param:Json(name = "amount_cents")
    val amountCents: Long?,
    @param:Json(name = "home_amount_cents")
    val homeAmountCents: Long? = null,
    @param:Json(name = "home_currency")
    val homeCurrency: String? = null,
    @param:Json(name = "original_currency")
    val originalCurrency: String? = null,
    @param:Json(name = "original_amount")
    val originalAmount: String? = null,
    @param:Json(name = "fx_rate")
    val fxRate: String? = null,
    @param:Json(name = "fx_rate_date")
    val fxRateDate: String? = null,
    @param:Json(name = "fx_source")
    val fxSource: String? = null,
    @param:Json(name = "fx_status")
    val fxStatus: String? = null,
    @param:Json(name = "original_currency_code")
    val originalCurrencyCode: String? = null,
    @param:Json(name = "original_amount_minor")
    val originalAmountMinor: Long? = null,
    @param:Json(name = "exchange_rate_to_cny")
    val exchangeRateToCny: String? = null,
    @param:Json(name = "exchange_rate_date")
    val exchangeRateDate: String? = null,
    @param:Json(name = "exchange_rate_source")
    val exchangeRateSource: String? = null,
    val merchant: String?,
    val category: String,
    @param:Json(name = "category_suggestion")
    val categorySuggestion: PendingCategorySuggestionDto? = null,
    @param:Json(name = "duplicate_candidates")
    val duplicateCandidates: List<PendingDuplicateCandidateDto> = emptyList(),
    val note: String?,
    val source: String,
    @param:Json(name = "image_path")
    val imagePath: String?,
    @param:Json(name = "thumbnail_path")
    val thumbnailPath: String?,
    @param:Json(name = "image_deleted_at")
    val imageDeletedAt: String? = null,
    @param:Json(name = "thumbnail_deleted_at")
    val thumbnailDeletedAt: String? = null,
    @param:Json(name = "image_hash")
    val imageHash: String?,
    @param:Json(name = "raw_text")
    val rawText: String?,
    val confidence: Double?,
    @param:Json(name = "duplicate_status")
    val duplicateStatus: String,
    @param:Json(name = "duplicate_of_id")
    val duplicateOfId: Long?,
    @param:Json(name = "duplicate_reason")
    val duplicateReason: String?,
    val tags: String?,
    @param:Json(name = "value_score")
    val valueScore: Int?,
    @param:Json(name = "regret_score")
    val regretScore: Int?,
    val status: String,
    @param:Json(name = "expense_time")
    val expenseTime: String?,
    @param:Json(name = "created_at")
    val createdAt: String,
    @param:Json(name = "updated_at")
    val updatedAt: String,
    @param:Json(name = "confirmed_at")
    val confirmedAt: String?,
    @param:Json(name = "rejected_at")
    val rejectedAt: String?,
)

data class ExpenseUpdateRequest(
    @param:Json(name = "expected_updated_at")
    val expectedUpdatedAt: String? = null,
    @param:Json(name = "original_currency")
    val originalCurrency: String? = null,
    @param:Json(name = "original_amount")
    val originalAmount: String? = null,
    @param:Json(name = "spent_at")
    val spentAt: String? = null,
    val merchant: String?,
    val category: String?,
    val note: String?,
    @param:Json(name = "expense_time")
    val expenseTime: String?,
    val tags: String?,
    @param:Json(name = "value_score")
    val valueScore: Int?,
    @param:Json(name = "regret_score")
    val regretScore: Int?,
)

/**
 * ADR-0038 PR-2b: optimistic-concurrency token shared by the
 * confirm / reject / mark-not-duplicate state-machine POSTs.
 *
 * Client passes the ``updatedAt`` of the last ``Expense`` snapshot it
 * saw. Backend ``UPDATE WHERE updated_at = expected_updated_at``
 * rejects stale writes with HTTP 409.
 */
data class ExpenseStateTokenRequest(
    @param:Json(name = "expected_updated_at")
    val expectedUpdatedAt: String,
)

data class NotificationDraftRequestDto(
    val source: String,
    @param:Json(name = "original_currency")
    val originalCurrency: String? = null,
    @param:Json(name = "original_amount")
    val originalAmount: String? = null,
    @param:Json(name = "spent_at")
    val spentAt: String? = null,
    val merchant: String?,
    val category: String?,
    @param:Json(name = "expense_time")
    val expenseTime: String?,
)

data class PaginatedExpensesDto(
    val items: List<ExpenseDto>,
    val page: Int,
    @param:Json(name = "page_size")
    val pageSize: Int,
    val total: Int,
)
