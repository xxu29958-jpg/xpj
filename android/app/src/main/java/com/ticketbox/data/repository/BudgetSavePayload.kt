package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonClass
import com.squareup.moshi.JsonDataException
import com.ticketbox.data.remote.dto.BudgetMonthlyUpdateRequestDto
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
)

internal fun monthlyBudgetTarget(month: String): String = "monthly_budget:$month"

internal fun JsonAdapter<BudgetSavePayload>.readSupportedBudgetSave(json: String): BudgetSavePayload? = try {
    fromJson(json)?.takeIf { payload ->
        payload.revision == 1 && payload.request.expectedRowVersion == null &&
            CurrencyCode.fromStorageKeyOrNull(payload.request.homeCurrencyCode) != null &&
            runCatching { ZoneId.of(payload.timezone)
                YearMonth.parse(payload.month).toString() == payload.month }.getOrDefault(false)
    }
} catch (_: JsonDataException) { null } catch (_: IOException) { null }
