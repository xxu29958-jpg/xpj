package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json

data class RecurringCandidateItemDto(
    val merchant: String,
    @param:Json(name = "amount_cents")
    val amountCents: Long,
    @param:Json(name = "occurrence_count")
    val occurrenceCount: Int,
    @param:Json(name = "last_seen_at")
    val lastSeenAt: String?,
    val confidence: String,
    val reason: String,
)

data class RecurringCandidatesResponseDto(
    val items: List<RecurringCandidateItemDto>,
)

data class DataQualitySummaryDto(
    @param:Json(name = "pending_total")
    val pendingTotal: Int,
    @param:Json(name = "missing_amount")
    val missingAmount: Int,
    @param:Json(name = "missing_merchant")
    val missingMerchant: Int,
    @param:Json(name = "missing_category")
    val missingCategory: Int,
    // N-1 compat: added after the field's first backend shipped — nullable with
    // a default so an old backend's payload (which omits them) still decodes;
    // null means "unknown composition, fall back to the aggregate caliber".
    @param:Json(name = "missing_category_pending")
    val missingCategoryPending: Int? = null,
    @param:Json(name = "missing_category_confirmed")
    val missingCategoryConfirmed: Int? = null,
    @param:Json(name = "suspected_duplicates")
    val suspectedDuplicates: Int,
    @param:Json(name = "confirmed_without_image")
    val confirmedWithoutImage: Int,
    @param:Json(name = "ready_to_confirm")
    val readyToConfirm: Int,
    @param:Json(name = "ready_to_confirm_categorized")
    val readyToConfirmCategorized: Int? = null,
    @param:Json(name = "oldest_pending_age_days")
    val oldestPendingAgeDays: Int?,
    @param:Json(name = "generated_at")
    val generatedAt: String,
)
