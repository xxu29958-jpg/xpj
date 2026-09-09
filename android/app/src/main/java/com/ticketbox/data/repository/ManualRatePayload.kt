package com.ticketbox.data.repository

import com.squareup.moshi.JsonClass
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.ExchangeRateDto
import com.ticketbox.data.remote.dto.ExchangeRateRequestDto
import com.ticketbox.domain.model.CurrencyCode
import java.time.LocalDate
import java.time.YearMonth

@JsonClass(generateAdapter = true)
data class ManualRatePayload(val revision: Int, val month: String,
    val originalPublicId: String?, val request: ExchangeRateRequestDto) {
    fun supports(row: OutboxRow): Boolean = isSupported() && row.type == PendingMutationType.SaveManualExchangeRate &&
        row.targetId == manualRateTarget(request) && row.expectedRowVersion == request.expectedRowVersion &&
        !row.idempotencyKey.isNullOrBlank()

    fun isSupported(): Boolean = revision == 1 && request.expectedRowVersion >= 0 &&
        (if (request.expectedRowVersion == 0L) originalPublicId == null else !originalPublicId.isNullOrBlank()) &&
        CurrencyCode.fromStorageKeyOrNull(request.currencyCode)?.storageKey == request.currencyCode &&
        CurrencyCode.fromStorageKeyOrNull(request.homeCurrencyCode)?.storageKey == request.homeCurrencyCode &&
        request.currencyCode != request.homeCurrencyCode && request.source == "manual" &&
        com.ticketbox.domain.model.canonicalManualExchangeRateOrNull(request.rateToHome) == request.rateToHome &&
        runCatching { YearMonth.parse(month).toString() == month && LocalDate.parse(request.rateDate).toString() == request.rateDate }.getOrDefault(false)

    fun accepts(row: OutboxRow, receipt: ExchangeRateDto): Boolean = supports(row) && receipt.publicId.isNotBlank() &&
        (originalPublicId == null || receipt.publicId == originalPublicId) &&
        receipt.currencyCode == request.currencyCode && receipt.homeCurrencyCode == request.homeCurrencyCode &&
        receipt.rateDate == request.rateDate && receipt.source == request.source &&
        receipt.rowVersion == row.expectedRowVersion + 1 &&
        receipt.rateToHome.toBigDecimalOrNull()?.compareTo(request.rateToHome.toBigDecimal()) == 0
}

data class PendingManualRateSubmission(val row: OutboxRow, val intent: ManualRatePayload?, val receipt: ExchangeRateDto?) {
    val isConfirmed: Boolean get() = row.status == PendingMutationStatus.Done && receipt != null
    val canRetry: Boolean get() = intent?.supports(row) == true && row.status == PendingMutationStatus.Failed &&
        (row.lastError?.startsWith("max_attempts_exceeded(") == true ||
            row.lastError in setOf("client_upgrade_required", "runtime_version_mismatch"))
    val canDrop: Boolean get() = row.status in setOf(PendingMutationStatus.Failed, PendingMutationStatus.Conflict) ||
        (row.status == PendingMutationStatus.Done && !isConfirmed)
}

internal fun manualRateTarget(request: ExchangeRateRequestDto) =
    "manual_rate:${request.currencyCode}:${request.homeCurrencyCode}:${request.rateDate}"
