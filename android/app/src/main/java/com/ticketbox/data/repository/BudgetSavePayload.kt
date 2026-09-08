package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonClass
import com.squareup.moshi.JsonDataException
import com.ticketbox.data.remote.dto.BudgetMonthlyUpdateRequestDto
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.domain.model.CurrencyCode
import java.io.IOException
import java.time.YearMonth
import java.time.ZoneId

@JsonClass(generateAdapter = true)
data class BudgetSavePayload(
    val revision: Int,
    val month: String,
    val timezone: String,
    val request: BudgetMonthlyUpdateRequestDto,
)

data class PendingBudgetSave(
    val row: OutboxRow,
    val intent: BudgetSavePayload?,
    val receipt: com.ticketbox.domain.model.BudgetMonthly?,
) {
    val hasSupportedIntent: Boolean get() = intent?.matches(row) == true
    val canRetry: Boolean get() = hasSupportedIntent && row.status == PendingMutationStatus.Failed &&
        row.lastError != BUDGET_CURRENCY_CONFLICT && row.lastError?.startsWith("outbox_row_expired") != true
}

internal const val BUDGET_CURRENCY_CONFLICT = "budget_currency_conflict"
internal const val BUDGET_SAVE_UNSUPPORTED = "budget_save_unsupported"
internal const val BUDGET_SAVE_UNVERIFIED = "budget_save_unverified"

internal fun monthlyBudgetTarget(month: String): String = "monthly_budget:$month"

internal fun JsonAdapter<BudgetSavePayload>.readSupportedBudgetSave(json: String): BudgetSavePayload? = try {
    fromJson(json)?.takeIf { it.isSupported() }
} catch (_: JsonDataException) { null } catch (_: IOException) { null }

internal fun BudgetSavePayload.matches(row: OutboxRow): Boolean = isSupported() &&
    row.type == PendingMutationType.SaveMonthlyBudget && row.targetId == monthlyBudgetTarget(month) &&
    row.expectedRowVersion >= 0 && !row.idempotencyKey.isNullOrBlank()

private fun BudgetSavePayload.isSupported(): Boolean = revision == 1 && request.expectedRowVersion == null &&
    CurrencyCode.fromStorageKeyOrNull(request.homeCurrencyCode) != null && runCatching {
        ZoneId.of(timezone)
        YearMonth.parse(month).toString() == month
    }.getOrDefault(false)
