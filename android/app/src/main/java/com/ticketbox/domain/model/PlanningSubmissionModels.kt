package com.ticketbox.domain.model

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class BillSplitInviteRequest(
    @param:Json(name = "receiver_account_id")
    val receiverAccountId: Long,
    @param:Json(name = "amount_cents")
    val amountCents: Long,
    @param:Json(name = "expected_row_version")
    val expectedRowVersion: Long,
)

@JsonClass(generateAdapter = true)
data class DebtGoalLinksReplaceRequest(
    @param:Json(name = "expected_row_version")
    val expectedRowVersion: Long,
    @param:Json(name = "debt_public_ids")
    val debtPublicIds: List<String>,
)

@JsonClass(generateAdapter = true)
data class DebtGoalTargetDateRequest(
    @param:Json(name = "expected_row_version")
    val expectedRowVersion: Long,
    @param:Json(name = "target_date")
    val targetDate: String? = null,
)

@JsonClass(generateAdapter = true)
data class GoalCreateRequest(
    val name: String,
    @param:Json(name = "goal_type")
    val goalType: String = "spending_limit",
    val period: String = "monthly",
    val month: String? = null,
    @param:Json(name = "target_amount_cents")
    val targetAmountCents: Long? = null,
    val category: String? = null,
    @param:Json(name = "debt_public_ids")
    val debtPublicIds: List<String>? = null,
    @param:Json(name = "home_currency_code")
    val homeCurrencyCode: String? = null,
)

@JsonClass(generateAdapter = true)
data class GoalUpdateRequest(
    @param:Json(name = "expected_row_version")
    val expectedRowVersion: Long,
    val name: String? = null,
    val month: String? = null,
    val category: String? = null,
    @param:Json(name = "target_amount_cents")
    val targetAmountCents: Long? = null,
    // Nullable only for reading an older durable submission; the writer validates it.
    @param:Json(name = "home_currency_code")
    val homeCurrencyCode: String? = null,
)

@JsonClass(generateAdapter = true)
data class IncomePlanUpdateRequest(
    @param:Json(name = "intent_month") val intentMonth: String,
    @param:Json(name = "expected_row_version") val expectedRowVersion: Long,
    val label: String? = null,
    @param:Json(name = "source_type") val sourceType: String? = null,
    val frequency: String? = null,
    @param:Json(name = "income_month") val incomeMonth: String? = null,
    @param:Json(name = "amount_cents") val amountCents: Long? = null,
    @param:Json(name = "pay_day") val payDay: Int? = null,
)
