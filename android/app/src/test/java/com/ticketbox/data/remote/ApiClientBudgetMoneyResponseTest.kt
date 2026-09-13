package com.ticketbox.data.remote

import com.ticketbox.data.repository.toDomain
import com.ticketbox.domain.model.toBudgetProgress
import com.ticketbox.notification.budget.BudgetOverspendDispatchOutcome
import com.ticketbox.notification.budget.NotifierBudgetOverspendDispatcher
import com.ticketbox.notification.budget.evaluateBudgetOverspend
import kotlinx.coroutines.test.runTest
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull

class ApiClientBudgetMoneyResponseTest {
    @Test
    fun missingConversionRemainsReadableWithoutInventingProgressOrNotification() = runTest {
        val budget = budgetMoneyApi(unknown = true).monthlyBudget("2026-09").toDomain()
        assertEquals(1200L, budget.totalAmountCents)
        assertNull(budget.spentAmountCents)
        assertNull(budget.categoryBudgets.single().remainingAmountCents)
        assertNull(budget.toBudgetProgress())
        assertNull(evaluateBudgetOverspend("owner", budget))
    }

    @Test
    fun notificationKeepsRecordedYenMinorUnits() = runTest {
        val budget = budgetMoneyApi(unknown = false).monthlyBudget("2026-09").toDomain()
        var amount: String? = null
        val notifier = NotifierBudgetOverspendDispatcher { value, _ ->
            amount = value
            BudgetOverspendDispatchOutcome.SENT
        }
        notifier.dispatch(assertNotNull(evaluateBudgetOverspend("owner", budget)))
        assertEquals("¥1,200", amount)
    }
}

private fun budgetMoneyApi(unknown: Boolean): ApiService {
    val spent = if (unknown) "null" else "2400"
    val remaining = if (unknown) "null" else "-1200"
    val overspent = if (unknown) "null" else "1200"
    val body = """{
        "ledger_id":"owner","month":"2026-09","configured":true,"row_version":3,
        "home_currency_code":"JPY","missing_currency_codes":["USD"],
        "total_amount_cents":1200,"rollover_amount_cents":0,"fixed_amount_cents":0,
        "non_monthly_amount_cents":0,"flex_budget_cents":1200,"spent_amount_cents":$spent,
        "excluded_amount_cents":0,"remaining_amount_cents":$remaining,"overspent_amount_cents":$overspent,
        "excluded_categories":[],"excluded_breakdown":[],"updated_at":null,
        "category_budgets":[{"category":"餐饮","amount_cents":1200,"spent_amount_cents":$spent,
        "remaining_amount_cents":$remaining,"overspent_amount_cents":$overspent}]
    }""".trimIndent()
    val client = OkHttpClient.Builder().addInterceptor { chain ->
        Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1)
            .code(200).message("OK").body(body.toResponseBody()).build()
    }.build()
    return buildApiService("https://example.test/", client)
}
