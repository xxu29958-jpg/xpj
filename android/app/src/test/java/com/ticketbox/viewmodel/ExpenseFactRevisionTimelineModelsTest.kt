package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseRevision
import com.ticketbox.domain.model.UiText
import kotlin.test.Test
import kotlin.test.assertEquals

class ExpenseFactRevisionTimelineModelsTest {
    @Test
    fun `original amount uses each revision snapshot currency exponent`() {
        val revision = ExpenseRevision(
            publicId = "revision-2",
            revisionNumber = 2,
            changeKind = "correction",
            reason = "修正原币金额",
            changedFields = listOf("original_currency_code", "original_amount_minor"),
            before = mapOf(
                "original_currency_code" to "JPY",
                "original_amount_minor" to 1_200L,
            ),
            after = mapOf(
                "original_currency_code" to "USD",
                "original_amount_minor" to 1_200L,
            ),
            actorAccountName = "我",
            actorDeviceName = "手机",
            createdAt = "2026-08-30T08:00:00Z",
        )

        val amountChange = listOf(revision)
            .toTimelineEntries(CurrencyCode.CNY)
            .single()
            .changes
            .single { (it.label as? UiText.Res)?.id == R.string.expense_fact_timeline_field_original_amount }

        assertEquals(UiText.raw("1200"), amountChange.before)
        assertEquals(UiText.raw("12.00"), amountChange.after)
    }

    @Test
    fun `amount-only correction derives the allocation state change from revision snapshots`() {
        val revision = ExpenseRevision(
            publicId = "revision-3",
            revisionNumber = 3,
            changeKind = "correction",
            reason = "账单金额应更高",
            changedFields = listOf("amount_cents"),
            before = mapOf(
                "amount_cents" to 1_200L,
                "splits" to listOf(mapOf("amount_cents" to 1_200L)),
            ),
            after = mapOf(
                "amount_cents" to 1_300L,
                "splits" to listOf(mapOf("amount_cents" to 1_200L)),
            ),
            actorAccountName = "我",
            actorDeviceName = "手机",
            createdAt = "2026-08-30T08:00:00Z",
        )

        val allocationChange = listOf(revision)
            .toTimelineEntries(CurrencyCode.CNY)
            .single()
            .changes
            .single { (it.label as? UiText.Res)?.id == R.string.expense_fact_timeline_field_splits }

        assertEquals(UiText.res(R.string.expense_fact_timeline_allocation_complete), allocationChange.before)
        assertEquals(
            UiText.res(R.string.expense_fact_timeline_allocation_remaining, "1.00"),
            allocationChange.after,
        )
    }
}
