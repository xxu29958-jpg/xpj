package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonClass
import com.squareup.moshi.JsonDataException
import com.ticketbox.domain.model.DebtVoidCreateRequest
import com.ticketbox.domain.model.RepaymentVoidCreateRequest
import java.io.IOException

@JsonClass(generateAdapter = true)
data class DebtVoidPayload(
    val revision: Int,
    override val subject: DebtWriteSubject,
    override val originSessionGeneration: String,
    override val originBindingRevision: String,
    val request: DebtVoidCreateRequest,
) : DebtWriteIntent { override val expectedRowVersion: Long get() = request.expectedRowVersion }

@JsonClass(generateAdapter = true)
data class DebtRepaymentVoidPayload(
    val revision: Int,
    override val subject: DebtWriteSubject,
    override val originSessionGeneration: String,
    override val originBindingRevision: String,
    val request: RepaymentVoidCreateRequest,
) : DebtWriteIntent { override val expectedRowVersion: Long get() = request.expectedRowVersion }

internal fun OutboxRow.readOriginalDebtVoid(adapter: JsonAdapter<DebtVoidPayload>): DebtVoidPayload? {
    val payload = adapter.readVoidPayload(payloadJson)?.takeIf {
        validVoid(it, it.revision, it.originSessionGeneration, it.originBindingRevision, it.request.reason)
    }
    return payload
}

internal fun OutboxRow.readOriginalRepaymentVoid(adapter: JsonAdapter<DebtRepaymentVoidPayload>): DebtRepaymentVoidPayload? {
    val payload = adapter.readVoidPayload(payloadJson)?.takeIf {
        it.request.repaymentPublicId.isNotBlank() && validVoid(it, it.revision,
            it.originSessionGeneration, it.originBindingRevision, it.request.reason)
    }
    return payload
}

private fun OutboxRow.validVoid(intent: DebtWriteIntent, revision: Int, session: String, binding: String,
    reason: String): Boolean = revision == 1 && intent.subject.publicId.isNotBlank() &&
    intent.subject.homeCurrencyCode.isNotBlank() && session.isNotBlank() && binding.isNotBlank() &&
    isDebtAdjustmentReasonValid(reason) && intent.expectedRowVersion > 0 && expectedRowVersion == intent.expectedRowVersion &&
    targetId == debtWriteTarget(intent.subject.publicId) && !idempotencyKey.isNullOrBlank()

private fun <T> JsonAdapter<T>.readVoidPayload(json: String): T? = try { fromJson(json) }
    catch (_: JsonDataException) { null } catch (_: IOException) { null }

internal fun OutboxRow.describeDebtVoid(adapter: JsonAdapter<DebtVoidPayload>): PendingDebtWrite =
    PendingDebtWrite(this, readOriginalDebtVoid(adapter)?.toView())

internal fun OutboxRow.describeRepaymentVoid(adapter: JsonAdapter<DebtRepaymentVoidPayload>): PendingDebtWrite =
    PendingDebtWrite(this, readOriginalRepaymentVoid(adapter)?.toView())
