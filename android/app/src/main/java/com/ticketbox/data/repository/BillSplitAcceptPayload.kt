package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonClass
import com.squareup.moshi.JsonDataException
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.remote.dto.BillSplitInboxDto
import com.ticketbox.domain.model.BillSplitInbox
import com.ticketbox.domain.model.CurrencyCode
import java.io.IOException

/** Original invitation and receiver choice. Room owns submission; this is never a received fact. */
@JsonClass(generateAdapter = true)
data class BillSplitAcceptPayload(
    val revision: Int = 1,
    val publicId: String,
    val amountCents: Long,
    val homeCurrencyCode: String,
    val senderName: String,
    val targetLedgerId: String,
    val targetLedgerName: String,
)

data class PendingBillSplitAcceptance(val row: OutboxRow, val payload: BillSplitAcceptPayload?, val invitation: BillSplitInbox?) {
    val delivered: Boolean get() = row.status == PendingMutationStatus.Done && invitation != null
    val canRetry: Boolean get() = payload != null && row.status == PendingMutationStatus.Failed &&
        row.lastError !in setOf("outbox_row_expired", "bill_split_accept_requires_review", "bill_split_accept_payload_unsupported")
}

data class BillSplitAcceptanceObservation(val access: LedgerAccessContext?, val submissions: List<PendingBillSplitAcceptance> = emptyList())

internal fun BillSplitInboxDto.accepts(original: BillSplitAcceptPayload): Boolean = publicId == original.publicId &&
    status == "accepted" && acceptedTargetLedgerId == original.targetLedgerId &&
    amountCents == original.amountCents && homeCurrencyCode == original.homeCurrencyCode &&
    (receivedBill == null || receivedBill.ledgerId == original.targetLedgerId && receivedBill.expenseId > 0)

internal fun JsonAdapter<BillSplitAcceptPayload>.readAcceptance(row: OutboxRow): BillSplitAcceptPayload? = try {
    fromJson(row.payloadJson)?.takeIf {
        it.revision == 1 && it.publicId.isNotBlank() && row.targetId == "bill-split:${it.publicId}" &&
            row.idempotencyKey == it.publicId && row.expectedRowVersion == 0L && it.amountCents > 0 &&
            it.targetLedgerId.isNotBlank() && CurrencyCode.fromStorageKeyOrNull(it.homeCurrencyCode) != null
    }
} catch (_: JsonDataException) {
    null
} catch (_: IOException) {
    null
}
