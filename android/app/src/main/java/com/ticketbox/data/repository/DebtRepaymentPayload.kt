package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonClass
import com.squareup.moshi.JsonDataException
import com.ticketbox.data.remote.dto.RepaymentCreateRequestDto
import com.ticketbox.domain.model.CurrencyCode
import java.io.IOException
import java.time.OffsetDateTime
import java.time.LocalDate
import java.time.format.DateTimeParseException

/** Original payment time and money are captured before publication, including while offline. */
@JsonClass(generateAdapter = true)
data class DebtRepaymentPayload(
    val revision: Int,
    override val subject: DebtWriteSubject,
    override val originSessionGeneration: String,
    override val originBindingRevision: String,
    val request: RepaymentCreateRequestDto,
) : DebtAmountIntent {
    override val amountCents: Long get() = request.amountCents
    override val expectedRowVersion: Long get() = request.expectedRowVersion
}

internal fun OutboxRow.readOriginalDebtRepayment(adapter: JsonAdapter<DebtRepaymentPayload>): DebtRepaymentPayload? {
    val intent = try {
        adapter.fromJson(payloadJson)?.takeIf {
            it.revision == 1 && it.subject.publicId.isNotBlank() &&
                CurrencyCode.fromStorageKeyOrNull(it.subject.homeCurrencyCode) != null &&
                it.originSessionGeneration.isNotBlank() && it.originBindingRevision.isNotBlank() &&
                it.expectedRowVersion > 0 && it.amountCents > 0 &&
                it.request.hasSupportedPaymentTime() &&
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
    return intent
}

/** Keep legacy instants readable; date-only intent must never acquire a fabricated instant. */
private fun RepaymentCreateRequestDto.hasSupportedPaymentTime(): Boolean {
    val input = timeInput ?: return paidAt?.let { OffsetDateTime.parse(it).year > 0 } == true
    if (paidAt != null || input.calendarRevision <= 0 || LocalDate.parse(input.userLocalDate).year <= 0) return false
    return when (input.precision) {
        "date_only" -> input.instantUtc == null
        "instant" -> input.instantUtc?.let { OffsetDateTime.parse(it).year > 0 } == true
        else -> false
    }
}

internal fun OutboxRow.describeDebtRepayment(adapter: JsonAdapter<DebtRepaymentPayload>): PendingDebtWrite =
    PendingDebtWrite(this, readOriginalDebtRepayment(adapter)?.toView())
