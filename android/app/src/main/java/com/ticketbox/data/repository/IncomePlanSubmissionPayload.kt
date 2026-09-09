package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonClass
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.IncomePlanCreateRequestDto
import com.ticketbox.data.remote.dto.IncomePlanDto
import com.ticketbox.data.remote.dto.IncomePlanUpdateRequestDto
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.IncomePlan
import com.ticketbox.domain.model.IncomeSourceType
import java.time.YearMonth

internal const val INCOME_PLAN_EDIT_PAYLOAD_REVISION = 1
internal const val INCOME_PLAN_CREATE_PAYLOAD_REVISION = 2

/** Revision 1 edit JSON is preserved byte for byte in Room; revision 2 captures a complete creation. */
@JsonClass(generateAdapter = true)
data class IncomePlanSubmissionPayload(
    val revision: Int,
    val planPublicId: String,
    val originalLabel: String,
    val originalAmountCents: Long,
    val homeCurrencyCode: String,
    val originSessionGeneration: String,
    val originBindingRevision: String,
    val request: IncomePlanUpdateRequestDto,
) {
    fun supports(row: OutboxRow): Boolean = isSupported() && !row.idempotencyKey.isNullOrBlank() && when (row.type) {
        PendingMutationType.CreateIncomePlan -> revision == INCOME_PLAN_CREATE_PAYLOAD_REVISION &&
            row.expectedRowVersion == 0L && row.targetId == "income_plan_create:${row.idempotencyKey}"
        PendingMutationType.UpdateIncomePlan -> revision == INCOME_PLAN_EDIT_PAYLOAD_REVISION &&
            row.expectedRowVersion > 0 && row.targetId == incomePlanTarget(planPublicId)
        else -> false
    }

    fun createRequest() = IncomePlanCreateRequestDto(request.intentMonth, requireNotNull(request.label),
        requireNotNull(request.sourceType), requireNotNull(request.frequency), request.incomeMonth,
        requireNotNull(request.amountCents), requireNotNull(request.payDay), homeCurrencyCode)

    fun acceptsReceipt(row: OutboxRow, receipt: IncomePlanDto): Boolean = supports(row) &&
        receipt.publicId.isNotBlank() && (row.type == PendingMutationType.CreateIncomePlan || receipt.publicId == planPublicId) &&
        receipt.rowVersion == row.expectedRowVersion + 1 && receipt.homeCurrencyCode == homeCurrencyCode &&
        receipt.label == (request.label ?: originalLabel) && receipt.amountCents == (request.amountCents ?: originalAmountCents) &&
        (request.sourceType == null || receipt.sourceType == request.sourceType) &&
        (request.frequency == null || receipt.frequency == request.frequency) &&
        (request.payDay == null || receipt.payDay == request.payDay) &&
        (request.incomeMonth == null || receipt.incomeMonth == request.incomeMonth) &&
        (request.frequency != "monthly" || receipt.incomeMonth == null) &&
        receipt.status == "active" && receipt.archivedAt == null

    internal fun isSupported(): Boolean = validMonth(request.intentMonth) && originalLabel.isNotBlank() &&
        originalAmountCents >= 0 && request.expectedRowVersion == 0L &&
        originSessionGeneration.isNotBlank() && originBindingRevision.isNotBlank() &&
        CurrencyCode.fromStorageKeyOrNull(homeCurrencyCode)?.storageKey == homeCurrencyCode &&
        validIncomeFields(request) && supportsRevision()

    private fun supportsRevision(): Boolean = when (revision) {
            INCOME_PLAN_EDIT_PAYLOAD_REVISION -> planPublicId.isNotBlank()
            INCOME_PLAN_CREATE_PAYLOAD_REVISION -> planPublicId.isEmpty() && request.label != null &&
                request.sourceType != null && request.frequency != null && request.amountCents != null && request.payDay != null &&
                originalLabel == request.label && originalAmountCents == request.amountCents &&
                (request.frequency != "one_time" || request.incomeMonth != null)
            else -> false
        }
}

data class PendingIncomePlanSubmission(val row: OutboxRow, val intent: IncomePlanSubmissionPayload?,
    val confirmed: IncomePlan? = null) {
    val hasSupportedIntent: Boolean get() = intent?.supports(row) == true
    val isConfirmed: Boolean get() = row.status == PendingMutationStatus.Done && confirmed != null
    val requiresReview: Boolean get() = row.status == PendingMutationStatus.Done && !isConfirmed
    val canRetry: Boolean get() = hasSupportedIntent && row.status == PendingMutationStatus.Failed &&
        (row.lastError?.startsWith("max_attempts_exceeded(") == true ||
            row.lastError in setOf("client_upgrade_required", "runtime_version_mismatch"))
    val canDrop: Boolean get() = requiresReview || row.status in setOf(PendingMutationStatus.Failed, PendingMutationStatus.Conflict)
}

internal fun incomePlanTarget(publicId: String): String = "income_plan:$publicId"

internal fun JsonAdapter<IncomePlanSubmissionPayload>.readSupportedIncomeSubmission(json: String): IncomePlanSubmissionPayload? =
    runCatching { fromJson(json)?.takeIf { it.isSupported() } }.getOrNull()

private fun validMonth(value: String): Boolean = value.length == 7 &&
    runCatching { YearMonth.parse(value).toString() == value }.getOrDefault(false)

private fun validIncomeFields(request: IncomePlanUpdateRequestDto): Boolean =
    (request.label == null || request.label.isNotBlank()) &&
        (request.amountCents == null || request.amountCents >= 0) && (request.payDay == null || request.payDay in 1..31) &&
        (request.sourceType == null || IncomeSourceType.entries.any { it.wireValue == request.sourceType }) &&
        (request.frequency == null || request.frequency in setOf("monthly", "one_time")) &&
        (request.incomeMonth == null || validMonth(request.incomeMonth))
