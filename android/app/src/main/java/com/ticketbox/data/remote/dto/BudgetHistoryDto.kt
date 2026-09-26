package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass
import com.ticketbox.domain.model.BudgetArrangement
import com.ticketbox.domain.model.BudgetCategoryArrangement
import com.ticketbox.domain.model.BudgetHistoryPage
import com.ticketbox.domain.model.BudgetRevision

@JsonClass(generateAdapter = true)
data class BudgetHistoryDto(
    @param:Json(name = "ledger_id") val ledgerId: String,
    val month: String,
    val items: List<BudgetRevisionDto>,
    @param:Json(name = "next_before_version") val nextBeforeVersion: Long?,
) {
    fun toDomain() = BudgetHistoryPage(ledgerId, month, items.map { it.toDomain() }, nextBeforeVersion)
}

@JsonClass(generateAdapter = true)
data class BudgetRevisionDto(
    @param:Json(name = "row_version") val rowVersion: Long,
    @param:Json(name = "change_kind") val changeKind: String,
    @param:Json(name = "recorded_at") val recordedAt: String,
    val snapshot: BudgetArrangementDto,
) {
    fun toDomain() = BudgetRevision(rowVersion, changeKind, recordedAt, snapshot.toDomain())
}

@JsonClass(generateAdapter = true)
data class BudgetArrangementDto(
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String?,
    @param:Json(name = "total_amount_cents") val totalAmountCents: Long,
    @param:Json(name = "non_monthly_amount_cents") val nonMonthlyAmountCents: Long,
    @param:Json(name = "rollover_amount_cents") val rolloverAmountCents: Long,
    @param:Json(name = "excluded_categories") val excludedCategories: List<String>,
    @param:Json(name = "category_budgets") val categoryBudgets: List<BudgetCategoryRequestDto>,
    val archived: Boolean,
) {
    fun toDomain() = BudgetArrangement(homeCurrencyCode, totalAmountCents, nonMonthlyAmountCents,
        rolloverAmountCents, excludedCategories, categoryBudgets.map {
            BudgetCategoryArrangement(it.category, it.amountCents)
        }, archived)
}
