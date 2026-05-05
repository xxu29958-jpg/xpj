package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json

data class AuthCheckDto(
    val status: String,
    @param:Json(name = "tenant_name")
    val tenantName: String? = null,
)

data class UploadResponseDto(
    val id: Long,
    @param:Json(name = "public_id")
    val publicId: String,
    val status: String,
    val message: String,
)

data class ExpenseDto(
    val id: Long,
    @param:Json(name = "public_id")
    val publicId: String? = null,
    @param:Json(name = "amount_cents")
    val amountCents: Long?,
    val merchant: String?,
    val category: String,
    val note: String?,
    val source: String,
    @param:Json(name = "image_path")
    val imagePath: String?,
    @param:Json(name = "thumbnail_path")
    val thumbnailPath: String?,
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
    @param:Json(name = "amount_cents")
    val amountCents: Long?,
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

data class PaginatedExpensesDto(
    val items: List<ExpenseDto>,
    val page: Int,
    @param:Json(name = "page_size")
    val pageSize: Int,
    val total: Int,
)

data class CategoryStatsDto(
    val category: String,
    @param:Json(name = "amount_cents")
    val amountCents: Long,
    val count: Int,
)

data class CategoriesDto(
    val items: List<String>,
)

data class MonthsDto(
    val items: List<String>,
)

data class MonthlyStatsDto(
    val month: String,
    @param:Json(name = "total_amount_cents")
    val totalAmountCents: Long,
    val count: Int,
    @param:Json(name = "by_category")
    val byCategory: List<CategoryStatsDto>,
)

data class CategoryRuleDto(
    val id: Long,
    val keyword: String,
    val category: String,
    val enabled: Boolean,
    val priority: Int,
    @param:Json(name = "created_at")
    val createdAt: String,
    @param:Json(name = "updated_at")
    val updatedAt: String,
)

data class CategoryRuleRequest(
    val keyword: String?,
    val category: String?,
    val enabled: Boolean?,
    val priority: Int?,
)

data class LifestyleStatsDto(
    val month: String,
    @param:Json(name = "ai_subscription_amount_cents")
    val aiSubscriptionAmountCents: Long,
    @param:Json(name = "digital_amount_cents")
    val digitalAmountCents: Long,
    @param:Json(name = "max_expense")
    val maxExpense: ExpenseDto?,
    @param:Json(name = "recent_7_days_amount_cents")
    val recent7DaysAmountCents: Long,
    @param:Json(name = "frequent_merchants")
    val frequentMerchants: List<FrequentMerchantDto>,
)

data class FrequentMerchantDto(
    val merchant: String,
    val count: Int,
)

data class ServerSettingsDto(
    @param:Json(name = "tenant_name")
    val tenantName: String,
    val status: String,
    @param:Json(name = "storage_status")
    val storageStatus: String,
    @param:Json(name = "pending_count")
    val pendingCount: Int,
    @param:Json(name = "confirmed_count")
    val confirmedCount: Int,
    @param:Json(name = "rejected_count")
    val rejectedCount: Int,
    @param:Json(name = "suspected_duplicate_count")
    val suspectedDuplicateCount: Int,
    @param:Json(name = "upload_storage_bytes")
    val uploadStorageBytes: Long,
    @param:Json(name = "latest_upload_at")
    val latestUploadAt: String?,
)
