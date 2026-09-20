package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonClass
import com.ticketbox.data.remote.dto.BillSplitChangeAcceptRequestDto
import com.ticketbox.data.remote.dto.BillSplitChangeCreateRequestDto

@JsonClass(generateAdapter = true)
data class SplitAgreementPayload(
    val revision: Int = 1,
    val operation: String,
    val originalDebtPublicId: String,
    val proposalPublicId: String? = null,
    val returnDebtPublicId: String? = null,
    val create: BillSplitChangeCreateRequestDto? = null,
    val accept: BillSplitChangeAcceptRequestDto? = null,
) {
    val expectedRowVersion: Long get() = create?.expectedRowVersion ?: accept?.expectedRowVersion ?: 0L
}

internal val SPLIT_SHARE_REFUSALS = setOf("split_total_exceeds_parent", "split_amount_exceeds_parent")

internal const val SPLIT_CREATE = "create_bill_split_change_proposal"
internal const val SPLIT_ACCEPT = "accept_bill_split_change_proposal"
internal const val SPLIT_REJECT = "reject_bill_split_change_proposal"
internal const val SPLIT_WITHDRAW = "withdraw_bill_split_change_proposal"

@JsonClass(generateAdapter = true)
data class SplitAgreementReceipt(val publicId: String, val status: String)

internal fun JsonAdapter<SplitAgreementPayload>.readSplitAgreement(row: OutboxRow): SplitAgreementPayload? =
    runCatching { fromJson(row.payloadJson) }.getOrNull()?.takeIf {
        it.revision == 1 && it.originalDebtPublicId.isNotBlank() &&
            row.targetId == debtWriteTarget(it.originalDebtPublicId) && !row.idempotencyKey.isNullOrBlank() &&
            row.expectedRowVersion == it.expectedRowVersion && it.hasSupportedCommand()
    }

private fun SplitAgreementPayload.hasSupportedCommand(): Boolean = when (operation) {
    SPLIT_CREATE -> create != null && accept == null && proposalPublicId == null && validCreate(create)
    SPLIT_ACCEPT -> !proposalPublicId.isNullOrBlank() && accept != null && create == null && accept.expectedRowVersion > 0
    SPLIT_REJECT, SPLIT_WITHDRAW -> !proposalPublicId.isNullOrBlank() && create == null && accept == null
    else -> false
}

private fun validCreate(request: BillSplitChangeCreateRequestDto): Boolean =
    request.expectedRowVersion > 0 && request.newShareAmountCents >= 0 && isDebtAdjustmentReasonValid(request.reason)
