package com.ticketbox.data.repository

import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.DebtBillCaptureDto
import com.ticketbox.data.remote.dto.DebtBillCaptureReceiptDto

@JsonClass(generateAdapter = true)
data class DebtBillCapturePayload(
    val revision: Int,
    val binding: LogicalSessionBinding,
    val creationKey: String,
    val captureKey: String,
    val file: UploadIntentFileDescriptor,
)

internal object DebtBillJson {
    private val moshi = Moshi.Builder().build()
    val payload = moshi.adapter(DebtBillCapturePayload::class.java)
    val receipt = moshi.adapter(DebtBillCaptureReceiptDto::class.java)
    val source = moshi.adapter(DebtBillCaptureDto::class.java)

    fun readPayload(json: String): DebtBillCapturePayload? = runCatching { payload.fromJson(json) }.getOrNull()
        ?.takeIf { it.revision == 1 && isUploadIntentFileKey(it.captureKey) && it.creationKey.isNotBlank() &&
            it.file.key == it.captureKey }

    fun readCommand(row: OutboxRow): DebtBillCapturePayload? = readPayload(row.payloadJson)?.takeIf {
        row.type == PendingMutationType.CaptureDebtBill && row.idempotencyKey == it.captureKey &&
            row.targetId == "debt_bill:${it.captureKey}" && row.expectedRowVersion == 0L &&
            row.ownerKey == it.binding.ownerKey && row.ledgerId == it.binding.ledgerId && row.serverUrl == it.binding.serverUrl
    }
}
