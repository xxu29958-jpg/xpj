package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonClass
import com.squareup.moshi.JsonDataException
import com.ticketbox.data.remote.dto.RepaymentCreateRequestDto
import com.ticketbox.domain.model.CurrencyCode
import java.io.IOException
import java.time.OffsetDateTime
import java.time.format.DateTimeParseException

/** Original payment time and money are captured before publication, including while offline. */
@JsonClass(generateAdapter = true)
data class DebtRepaymentPayload(
    val revision: Int,
    override val subject: DebtWriteSubject,
    val originSessionGeneration: String,
    val originBindingRevision: String,
    val request: RepaymentCreateRequestDto,
) : DebtWriteIntent {
    override val amountCents: Long get() = request.amountCents
    override val expectedRowVersion: Long get() = request.expectedRowVersion
}

internal fun OutboxRow.describeDebtRepayment(adapter: JsonAdapter<DebtRepaymentPayload>): PendingDebtWrite {
    val intent = try {
        adapter.fromJson(payloadJson)?.takeIf {
            it.revision == 1 && it.subject.publicId.isNotBlank() &&
                CurrencyCode.fromStorageKeyOrNull(it.subject.homeCurrencyCode) != null &&
                it.originSessionGeneration.isNotBlank() && it.originBindingRevision.isNotBlank() &&
                it.expectedRowVersion > 0 && it.amountCents > 0 &&
                OffsetDateTime.parse(it.request.paidAt).year > 0 &&
                targetId == debtWriteTarget(it.subject.publicId) &&
                expectedRowVersion == it.expectedRowVersion && !idempotencyKey.isNullOrBlank()
        }
    } catch (_: JsonDataException) {
        null
    } catch (_: IOException) {
        null
    } catch (_: DateTimeParseException) {
        null
    }
    return PendingDebtWrite(this, intent)
}
