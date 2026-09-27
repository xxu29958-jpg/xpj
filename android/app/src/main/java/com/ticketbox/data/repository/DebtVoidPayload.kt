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
        validVoid(it, it.revision, it.originSessionGeneration, it.originBindingRevision, it.request.reason)
    }
    return PendingDebtWrite(this, payload)
}

internal fun OutboxRow.describeRepaymentVoid(adapter: JsonAdapter<DebtRepaymentVoidPayload>): PendingDebtWrite {
    val payload = adapter.readVoidPayload(payloadJson)?.takeIf {
        it.request.repaymentPublicId.isNotBlank() && validVoid(it, it.revision,
            it.originSessionGeneration, it.originBindingRevision, it.request.reason)
    }
    return PendingDebtWrite(this, payload)
}

private fun OutboxRow.validVoid(intent: DebtWriteIntent, revision: Int, session: String, binding: String,
    reason: String): Boolean = revision == 1 && intent.subject.publicId.isNotBlank() &&
    intent.subject.homeCurrencyCode.isNotBlank() && session.isNotBlank() && binding.isNotBlank() &&
    isDebtAdjustmentReasonValid(reason) && intent.expectedRowVersion > 0 && expectedRowVersion == intent.expectedRowVersion &&
    targetId == debtWriteTarget(intent.subject.publicId) && !idempotencyKey.isNullOrBlank()

private fun <T> JsonAdapter<T>.readVoidPayload(json: String): T? = try { fromJson(json) }
    catch (_: JsonDataException) { null } catch (_: IOException) { null }

/** Credential rotation retains these axes; a new logical binding cannot adopt the original command. */
internal fun DebtWriteIntent.matchesVoidOrigin(binding: LogicalSessionBinding): Boolean = when (this) {
    is DebtVoidPayload -> originSessionGeneration == binding.sessionGeneration && originBindingRevision == binding.bindingRevision
    is DebtRepaymentVoidPayload -> originSessionGeneration == binding.sessionGeneration && originBindingRevision == binding.bindingRevision
    else -> true
}
