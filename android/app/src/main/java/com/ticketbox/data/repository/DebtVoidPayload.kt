package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonClass
import com.squareup.moshi.JsonDataException
import com.ticketbox.data.remote.dto.DebtVoidCreateRequestDto
import com.ticketbox.data.remote.dto.RepaymentVoidCreateRequestDto
import java.io.IOException

@JsonClass(generateAdapter = true)
data class DebtVoidPayload(
    val revision: Int,
    override val subject: DebtWriteSubject,
    val originSessionGeneration: String,
    val originBindingRevision: String,
    val request: DebtVoidCreateRequestDto,
) : DebtWriteIntent { override val expectedRowVersion: Long get() = request.expectedRowVersion }

@JsonClass(generateAdapter = true)
data class DebtRepaymentVoidPayload(
    val revision: Int,
    override val subject: DebtWriteSubject,
    val originSessionGeneration: String,
    val originBindingRevision: String,
    val request: RepaymentVoidCreateRequestDto,
) : DebtWriteIntent { override val expectedRowVersion: Long get() = request.expectedRowVersion }

internal fun OutboxRow.describeDebtVoid(adapter: JsonAdapter<DebtVoidPayload>): PendingDebtWrite {
    val payload = adapter.readVoidPayload(payloadJson)?.takeIf {
        validVoid(it.revision, it.subject, it.originSessionGeneration, it.originBindingRevision, it.request.reason,
            it.expectedRowVersion)
    }
    return PendingDebtWrite(this, payload)
}

internal fun OutboxRow.describeRepaymentVoid(adapter: JsonAdapter<DebtRepaymentVoidPayload>): PendingDebtWrite {
    val payload = adapter.readVoidPayload(payloadJson)?.takeIf {
        it.request.repaymentPublicId.isNotBlank() && validVoid(it.revision, it.subject,
            it.originSessionGeneration, it.originBindingRevision, it.request.reason, it.expectedRowVersion)
    }
    return PendingDebtWrite(this, payload)
}

private fun OutboxRow.validVoid(revision: Int, subject: DebtWriteSubject, session: String, binding: String,
    reason: String, version: Long): Boolean = revision == 1 && subject.publicId.isNotBlank() &&
    subject.homeCurrencyCode.isNotBlank() && session.isNotBlank() && binding.isNotBlank() &&
    isDebtAdjustmentReasonValid(reason) && version > 0 && expectedRowVersion == version &&
    targetId == debtWriteTarget(subject.publicId) && !idempotencyKey.isNullOrBlank()

private fun <T> JsonAdapter<T>.readVoidPayload(json: String): T? = try { fromJson(json) }
    catch (_: JsonDataException) { null } catch (_: IOException) { null }
