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
    val intent: BudgetSaveSubmission?,
    val receipt: com.ticketbox.domain.model.BudgetMonthly?,
) {
    internal constructor(row: OutboxRow, intent: BudgetSavePayload?, receipt: com.ticketbox.domain.model.BudgetMonthly?) :
        this(row, intent?.toView(), receipt)
    val requiresReadRefresh: Boolean get() = row.requiresBudgetReadRefresh()
    val hasSupportedIntent: Boolean get() = intent?.matches(row) == true
    val canRetry: Boolean get() = hasSupportedIntent && row.status == PendingMutationStatus.Failed &&
        row.lastError != BUDGET_CURRENCY_CONFLICT && row.lastError?.startsWith("outbox_row_expired") != true
}

internal const val BUDGET_CURRENCY_CONFLICT = "budget_currency_conflict"
internal const val BUDGET_SAVE_UNSUPPORTED = "budget_save_unsupported"
internal const val BUDGET_SAVE_UNVERIFIED = "budget_save_unverified"
internal const val BUDGET_READ_REFRESH_REQUIRED = "budget_read_refresh_required"

internal fun OutboxRow.requiresBudgetReadRefresh(): Boolean =
    type == PendingMutationType.SaveMonthlyBudget && status == PendingMutationStatus.Done &&
        lastError == BUDGET_READ_REFRESH_REQUIRED && receiptJson != null

internal fun monthlyBudgetTarget(month: String): String = "monthly_budget:$month"

internal fun JsonAdapter<BudgetSavePayload>.readSupportedBudgetSave(json: String): BudgetSavePayload? = try {
    fromJson(json)?.takeIf { it.toView().isSupported() }
} catch (_: JsonDataException) { null } catch (_: IOException) { null }

internal fun BudgetSavePayload.matches(row: OutboxRow): Boolean = toView().matches(row)

private fun BudgetSaveSubmission.matches(row: OutboxRow): Boolean = isSupported() &&
    row.type == PendingMutationType.SaveMonthlyBudget && row.targetId == monthlyBudgetTarget(month) &&
    row.expectedRowVersion >= 0 && !row.idempotencyKey.isNullOrBlank()

private fun BudgetSaveSubmission.isSupported(): Boolean = revision == 1 && request.expectedRowVersion == null &&
    CurrencyCode.fromStorageKeyOrNull(request.homeCurrencyCode) != null && runCatching {
        ZoneId.of(timezone)
        YearMonth.parse(month).toString() == month
    }.getOrDefault(false)

data class BudgetSaveSubmission(
    val revision: Int,
    val month: String,
    val timezone: String,
    val request: com.ticketbox.domain.model.BudgetMonthlyUpdate,
)

internal fun BudgetSavePayload.toView() = BudgetSaveSubmission(
    revision = revision,
    month = month,
    timezone = timezone,
    request = request.toDomain(),
)
