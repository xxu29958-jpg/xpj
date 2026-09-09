package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonClass
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.CategoryRuleDto
import com.ticketbox.data.remote.dto.CategoryRuleRequest
import com.ticketbox.data.remote.dto.CategoryRuleUpdateRequest
import com.ticketbox.domain.model.CategoryRule
import com.ticketbox.domain.model.CurrencyCode

@JsonClass(generateAdapter = true)
data class CategoryRuleSubmissionPayload(
    val version: Int = 1,
    val expectedRowVersion: Long,
    val request: CategoryRuleRequest,
) {
    fun supports(row: OutboxRow): Boolean = version == 1 && expectedRowVersion == row.expectedRowVersion &&
        !row.idempotencyKey.isNullOrBlank() && (request.isCompleteRule() ||
            row.type == PendingMutationType.DeleteCategoryRule && !request.keyword.isNullOrBlank() && !request.category.isNullOrBlank()) && when (row.type) {
            PendingMutationType.CreateCategoryRule -> expectedRowVersion == 0L && row.targetId == "category_rule_create:${row.idempotencyKey}"
            PendingMutationType.UpdateCategoryRule, PendingMutationType.DeleteCategoryRule -> expectedRowVersion > 0 && row.ruleId() != null
            else -> false
        }

    fun updateRequest(): CategoryRuleUpdateRequest = CategoryRuleUpdateRequest(
        expectedRowVersion, request.keyword, request.category, request.enabled, request.priority,
        request.amountMinCents, request.amountMaxCents, request.sourceContains, request.tagContains, request.homeCurrencyCode,
    )

    fun acceptsReceipt(row: OutboxRow, receipt: CategoryRuleDto): Boolean = supports(row) &&
        receipt.id > 0 && (row.type == PendingMutationType.CreateCategoryRule || receipt.id == row.ruleId()) &&
        receipt.rowVersion == expectedRowVersion + 1 && receipt.asRequest() == request
}

data class PendingCategoryRuleSubmission(
    val row: OutboxRow,
    val request: CategoryRuleRequest?,
    val confirmed: CategoryRule?,
    val supported: Boolean,
) {
    val ruleId: Long? get() = row.ruleId() ?: confirmed?.id
    val isDone: Boolean get() = row.status == PendingMutationStatus.Done
    val canRetry: Boolean get() = supported && row.status == PendingMutationStatus.Failed &&
        (row.lastError?.startsWith("max_attempts_exceeded(") == true ||
            row.lastError in setOf("client_upgrade_required", "runtime_version_mismatch"))
    val canDrop: Boolean get() = row.status in setOf(PendingMutationStatus.Failed, PendingMutationStatus.Conflict)
}

internal fun describeCategoryRuleSubmission(
    row: OutboxRow,
    payloadAdapter: JsonAdapter<CategoryRuleSubmissionPayload>,
    legacyAdapter: JsonAdapter<CategoryRuleUpdateRequest>,
    receiptAdapter: JsonAdapter<CategoryRuleDto>,
): PendingCategoryRuleSubmission {
    val payload = runCatching { payloadAdapter.fromJson(row.payloadJson) }.getOrNull()
    val legacy = if (payload == null) runCatching { legacyAdapter.fromJson(row.payloadJson) }.getOrNull() else null
    val request = payload?.request ?: legacy?.let {
        CategoryRuleRequest(it.keyword, it.category, it.enabled, it.priority, it.amountMinCents,
            it.amountMaxCents, it.sourceContains, it.tagContains, it.homeCurrencyCode)
    }
    val receipt = row.receiptJson?.let { runCatching { receiptAdapter.fromJson(it) }.getOrNull() }
    val confirmed = receipt?.takeIf { payload?.acceptsReceipt(row, it) == true }?.toDomain()
    return PendingCategoryRuleSubmission(row, request, confirmed, payload?.supports(row) == true)
}

internal fun OutboxRow.ruleId(): Long? = targetId.takeIf { it.startsWith("category_rule:") }
    ?.removePrefix("category_rule:")?.toLongOrNull()?.takeIf { it > 0 }

internal fun CategoryRuleRequest.isCompleteRule(): Boolean =
    !keyword.isNullOrBlank() && !category.isNullOrBlank() && enabled != null && priority != null && hasValidAmountCondition()

private fun CategoryRuleRequest.hasValidAmountCondition(): Boolean {
    val currencyKnown = if (homeCurrencyCode == null) amountMinCents == null && amountMaxCents == null
        else CurrencyCode.fromStorageKeyOrNull(homeCurrencyCode)?.storageKey == homeCurrencyCode
    val lower = amountMinCents ?: 0L
    val upper = amountMaxCents ?: Long.MAX_VALUE
    return currencyKnown && lower >= 0 && upper >= lower
}

internal fun CategoryRule.asRequest(): CategoryRuleRequest = CategoryRuleRequest(
    keyword, category, enabled, priority, amountMinCents, amountMaxCents, sourceContains, tagContains, homeCurrencyCode,
)

internal fun CategoryRuleDto.asRequest(): CategoryRuleRequest = CategoryRuleRequest(
    keyword, category, enabled, priority, amountMinCents, amountMaxCents, sourceContains, tagContains, homeCurrencyCode,
)
