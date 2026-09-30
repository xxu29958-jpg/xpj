package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonClass
import com.squareup.moshi.JsonDataException
import com.ticketbox.data.remote.dto.RepaymentDraftConfirmRequestDto
import java.io.IOException

/** The original selected Debt, OCC and reviewed money travel together through the existing Outbox. */
@JsonClass(generateAdapter = true)
data class RepaymentReviewPayload(
    val revision: Int,
    val draftPublicId: String,
    override val subject: DebtWriteSubject,
    override val originSessionGeneration: String,
    override val originBindingRevision: String,
    val request: RepaymentDraftConfirmRequestDto,
    val reviewedCurrency: String,
    val reviewedAmount: String,
) : DebtWriteIntent {
    override val expectedRowVersion: Long get() = request.expectedRowVersion
}

@JsonClass(generateAdapter = true)
data class RepaymentDismissPayload(val revision: Int, val draftPublicId: String, val binding: LogicalSessionBinding)

internal fun OutboxRow.describeRepaymentReview(adapter: JsonAdapter<RepaymentReviewPayload>): PendingDebtWrite {
    val intent = try {
        adapter.fromJson(payloadJson)?.takeIf {
            it.revision == 1 && it.draftPublicId.isNotBlank() && it.subject.publicId == it.request.targetDebtPublicId &&
                it.originSessionGeneration.isNotBlank() && it.originBindingRevision.isNotBlank() &&
                it.expectedRowVersion > 0 && targetId == debtWriteTarget(it.subject.publicId) &&
                expectedRowVersion == it.expectedRowVersion && !idempotencyKey.isNullOrBlank()
        }
    } catch (_: JsonDataException) {
        null
    } catch (_: IOException) {
        null
    }
    return PendingDebtWrite(this, intent)
}
