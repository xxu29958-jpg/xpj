package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json

data class AuthCheckDto(
    val status: String,
    @param:Json(name = "account_name")
    val accountName: String,
    @param:Json(name = "ledger_id")
    val ledgerId: String,
    @param:Json(name = "ledger_name")
    val ledgerName: String,
    @param:Json(name = "device_name")
    val deviceName: String,
    val role: String,
    val scope: String,
)

data class PairRequestDto(
    @param:Json(name = "pairing_code")
    val pairingCode: String,
    @param:Json(name = "device_name")
    val deviceName: String,
    val platform: String,
)

data class PairResponseDto(
    @param:Json(name = "session_token")
    val sessionToken: String,
    @param:Json(name = "account_name")
    val accountName: String,
    @param:Json(name = "ledger_id")
    val ledgerId: String,
    @param:Json(name = "ledger_name")
    val ledgerName: String,
    @param:Json(name = "device_name")
    val deviceName: String,
    val role: String,
)

data class StatusDto(
    val status: String,
)

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

data class NotificationDraftRequestDto(
    val source: String,
    @param:Json(name = "amount_cents")
    val amountCents: Long?,
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

data class CategoryStatsDto(
    val category: String,
    @param:Json(name = "amount_cents")
    val amountCents: Long,
    val count: Int,
)

data class TagStatsDto(
    val tag: String,
    @param:Json(name = "amount_cents")
    val amountCents: Long,
    val count: Int,
)

data class CategoriesDto(
    val items: List<String>,
)

data class TagsDto(
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
    @param:Json(name = "by_tag")
    val byTag: List<TagStatsDto> = emptyList(),
)

data class CategoryRuleDto(
    val id: Long,
    val keyword: String,
    val category: String,
    val enabled: Boolean,
    val priority: Int,
    @param:Json(name = "amount_min_cents")
    val amountMinCents: Long? = null,
    @param:Json(name = "amount_max_cents")
    val amountMaxCents: Long? = null,
    @param:Json(name = "source_contains")
    val sourceContains: String? = null,
    @param:Json(name = "tag_contains")
    val tagContains: String? = null,
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
    @param:Json(name = "amount_min_cents")
    val amountMinCents: Long? = null,
    @param:Json(name = "amount_max_cents")
    val amountMaxCents: Long? = null,
    @param:Json(name = "source_contains")
    val sourceContains: String? = null,
    @param:Json(name = "tag_contains")
    val tagContains: String? = null,
)

data class MerchantAliasDto(
    @param:Json(name = "public_id")
    val publicId: String,
    @param:Json(name = "canonical_merchant")
    val canonicalMerchant: String,
    @param:Json(name = "canonical_key")
    val canonicalKey: String,
    val alias: String,
    @param:Json(name = "alias_key")
    val aliasKey: String,
    val enabled: Boolean,
    @param:Json(name = "created_at")
    val createdAt: String,
    @param:Json(name = "updated_at")
    val updatedAt: String,
)

data class MerchantAliasListDto(
    val items: List<MerchantAliasDto>,
)

data class MerchantAliasRequest(
    @param:Json(name = "canonical_merchant")
    val canonicalMerchant: String? = null,
    val alias: String? = null,
    val enabled: Boolean? = null,
)

data class RuleApplicationBatchDto(
    @param:Json(name = "public_id")
    val publicId: String,
    val status: String,
    @param:Json(name = "pending_scanned")
    val pendingScanned: Int,
    @param:Json(name = "changed_count")
    val changedCount: Int,
    @param:Json(name = "created_at")
    val createdAt: String,
    @param:Json(name = "rolled_back_at")
    val rolledBackAt: String? = null,
)

data class RuleApplicationListDto(
    val items: List<RuleApplicationBatchDto>,
)

data class RuleApplicationRollbackDto(
    @param:Json(name = "public_id")
    val publicId: String,
    val status: String,
    val changed: Int,
    val skipped: Int,
    @param:Json(name = "rolled_back_at")
    val rolledBackAt: String? = null,
)

data class RuleApplyConfirmedRequestDto(
    val confirm: Boolean = false,
    @param:Json(name = "preview_token")
    val previewToken: String? = null,
)

data class RuleApplyPreviewItemDto(
    val id: Long,
    val merchant: String?,
    @param:Json(name = "current_category")
    val currentCategory: String,
    @param:Json(name = "suggested_category")
    val suggestedCategory: String,
    @param:Json(name = "rule_keyword")
    val ruleKeyword: String,
    val reason: String,
)

data class RuleApplyConfirmedResponseDto(
    @param:Json(name = "dry_run")
    val dryRun: Boolean,
    @param:Json(name = "confirmed_scanned")
    val confirmedScanned: Int,
    @param:Json(name = "changed_count")
    val changedCount: Int,
    val items: List<RuleApplyPreviewItemDto> = emptyList(),
    @param:Json(name = "skipped_non_default_category")
    val skippedNonDefaultCategory: Int = 0,
    @param:Json(name = "no_match_count")
    val noMatchCount: Int = 0,
    @param:Json(name = "unchanged_count")
    val unchangedCount: Int = 0,
    @param:Json(name = "conflict_count")
    val conflictCount: Int = 0,
    @param:Json(name = "scan_limit_reached")
    val scanLimitReached: Boolean = false,
    @param:Json(name = "scan_limit")
    val scanLimit: Int = 0,
    @param:Json(name = "preview_token")
    val previewToken: String? = null,
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
    @param:Json(name = "account_name")
    val accountName: String,
    @param:Json(name = "ledger_id")
    val ledgerId: String? = null,
    @param:Json(name = "ledger_name")
    val ledgerName: String,
    @param:Json(name = "ledger_is_default")
    val ledgerIsDefault: Boolean? = null,
    @param:Json(name = "device_name")
    val deviceName: String,
    val role: String,
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
