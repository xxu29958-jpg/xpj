package com.ticketbox.data.repository

import com.squareup.moshi.JsonClass
import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.MonthlyArrangementSaveRequest
import com.ticketbox.data.remote.dto.MonthlyArrangementDto
import com.ticketbox.domain.model.CurrencyCode

@JsonClass(generateAdapter = true)
data class MonthlyArrangementPayload(val revision: Int, val month: String, val request: MonthlyArrangementSaveRequest) {
    fun supports(row: OutboxRow): Boolean = revision == 1 && validatedBudgetMonth(month).getOrNull() == month &&
        request.expectedRowVersion == null && request.savingsTargetCents in 0..com.ticketbox.domain.model.MONEY_MINOR_MAX && request.reservedBufferCents in 0..com.ticketbox.domain.model.MONEY_MINOR_MAX &&
        CurrencyCode.fromStorageKeyOrNull(request.homeCurrencyCode)?.storageKey == request.homeCurrencyCode &&
        row.type == PendingMutationType.SaveMonthlyArrangement && row.targetId == "monthly_arrangement:$month" &&
        row.expectedRowVersion >= 0 && !row.idempotencyKey.isNullOrBlank()
}
internal fun JsonAdapter<MonthlyArrangementPayload>.readArrangement(json: String): MonthlyArrangementPayload? =
    runCatching { fromJson(json) }.getOrNull()
data class PendingMonthlyArrangement(val row: OutboxRow, val intent: MonthlyArrangementPayload?, val receipt: MonthlyArrangementDto?) {
    val isConfirmed: Boolean get() = row.status == PendingMutationStatus.Done && receipt != null
    val canRetry: Boolean get() = intent?.supports(row) == true && row.status == PendingMutationStatus.Failed &&
        row.lastError?.startsWith("outbox_row_expired") != true
    val canDrop: Boolean get() = row.status == PendingMutationStatus.Failed || row.status == PendingMutationStatus.Conflict
}
