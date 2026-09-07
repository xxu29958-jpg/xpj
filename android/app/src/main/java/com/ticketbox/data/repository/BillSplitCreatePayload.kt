package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonClass
import com.squareup.moshi.JsonDataException
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.remote.dto.BillSplitInviteRequestDto
import java.io.IOException

/** The original reviewed source and recipient survive retries and process recreation. */
@JsonClass(generateAdapter = true)
data class BillSplitCreatePayload(
    val revision: Int,
    val expenseId: Long,
    val merchant: String?,
    val receiverName: String,
    val homeCurrencyCode: String,
    val request: BillSplitInviteRequestDto,
)

data class PendingBillSplitCreation(
    val row: OutboxRow,
    val payload: BillSplitCreatePayload?,
    val invitation: com.ticketbox.domain.model.BillSplitSent? = null,
) {
    val delivered: Boolean get() = row.status == PendingMutationStatus.Done
    val canRetry: Boolean get() = payload != null && row.status == PendingMutationStatus.Failed &&
        row.lastError !in setOf("outbox_row_expired", "bill_split_requires_review", "bill_split_payload_unsupported", "bill_split_intent_invalid")
}

data class BillSplitCreationObservation(
    val access: LedgerAccessContext?,
    val submissions: List<PendingBillSplitCreation> = emptyList(),
)

internal fun JsonAdapter<BillSplitCreatePayload>.readBillSplitIntent(row: OutboxRow): BillSplitCreatePayload? = try {
    fromJson(row.payloadJson)?.takeIf {
        it.revision == 1 && it.expenseId > 0 && row.targetId == "expense:${it.expenseId}" &&
            it.request.expectedRowVersion == row.expectedRowVersion && row.expectedRowVersion > 0 &&
            it.request.amountCents > 0 && it.request.receiverAccountId > 0 &&
            com.ticketbox.domain.model.CurrencyCode.fromStorageKeyOrNull(it.homeCurrencyCode) != null
    }
} catch (_: JsonDataException) {
    null
} catch (_: IOException) {
    null
}
