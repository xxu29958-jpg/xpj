package com.ticketbox.data.repository

import com.squareup.moshi.Moshi
import com.ticketbox.data.remote.dto.CategoryRuleDeleteRequest
import com.ticketbox.data.remote.dto.CategoryRuleUpdateRequest
import com.ticketbox.data.remote.dto.ExpenseItemReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseItemRequestDto
import com.ticketbox.data.remote.dto.ExpenseManualCreateRequestDto
import com.ticketbox.data.remote.dto.ExpenseRecognizeTextRequestDto
import com.ticketbox.data.remote.dto.ExpenseSplitReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseSplitRequestDto
import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import com.ticketbox.data.remote.dto.GoalUpdateRequestDto
import com.ticketbox.data.remote.dto.IncomePlanUpdateRequestDto
import com.ticketbox.data.remote.dto.MerchantAliasDeleteRequest
import com.ticketbox.data.remote.dto.MerchantAliasUpdateRequest
import kotlin.test.Test
import kotlin.test.assertEquals

class OutboxPayloadCodegenAdapterTest {
    private val moshi = Moshi.Builder().build()

    @Test
    fun outboxPayloadAdaptersRoundTripWithoutKotlinReflectFactory() {
        assertEquals(
            "codex shop",
            roundTrip(
                ExpenseUpdateRequest(
                    expectedRowVersion = 12L,
                    originalCurrency = "CNY",
                    originalAmount = "12.34",
                    spentAt = "2026-07-04T10:00:00+08:00",
                    merchant = "codex shop",
                    category = "food",
                    note = "note",
                    expenseTime = "2026-07-04T10:00:00+08:00",
                    tags = "lunch",
                    valueScore = 4,
                    regretScore = 1,
                ),
            ).merchant,
        )
        assertEquals("client-ref", roundTrip(manualCreateRequest()).clientRef)
        assertEquals(12L, roundTrip(ExpenseStateTokenRequest(expectedRowVersion = 12L)).expectedRowVersion)
        assertEquals("receipt text", roundTrip(ExpenseRecognizeTextRequestDto(12L, "receipt text")).rawText)
        assertEquals("tea", roundTrip(itemReplaceRequest()).items.single().name)
        assertEquals(1234L, roundTrip(splitReplaceRequest()).splits.single().amountCents)
        assertEquals("food", roundTrip(categoryRuleUpdateRequest()).category)
        assertEquals(12L, roundTrip(CategoryRuleDeleteRequest(expectedRowVersion = 12L)).expectedRowVersion)
        assertEquals("alias", roundTrip(MerchantAliasUpdateRequest(12L, "canonical", "alias", true)).alias)
        assertEquals(12L, roundTrip(MerchantAliasDeleteRequest(expectedRowVersion = 12L)).expectedRowVersion)
        assertEquals("goal", roundTrip(GoalUpdateRequestDto(12L, name = "goal")).name)
        assertEquals("salary", roundTrip(IncomePlanUpdateRequestDto(12L, label = "salary")).label)
    }

    private inline fun <reified T : Any> roundTrip(value: T): T {
        val adapter = moshi.adapter(T::class.java)
        return requireNotNull(adapter.fromJson(adapter.toJson(value)))
    }

    private fun manualCreateRequest(): ExpenseManualCreateRequestDto =
        ExpenseManualCreateRequestDto(
            originalCurrency = "CNY",
            originalAmount = "12.34",
            spentAt = "2026-07-04T10:00:00+08:00",
            merchant = "codex shop",
            category = "food",
            note = "note",
            expenseTime = "2026-07-04T10:00:00+08:00",
            tags = "lunch",
            valueScore = 4,
            regretScore = 1,
            clientRef = "client-ref",
        )

    private fun itemReplaceRequest(): ExpenseItemReplaceRequestDto =
        ExpenseItemReplaceRequestDto(
            expectedRowVersion = 12L,
            items = listOf(
                ExpenseItemRequestDto(
                    kind = "product",
                    name = "tea",
                    quantityText = "1",
                    unitPriceCents = 1234L,
                    amountCents = 1234L,
                    category = "food",
                    rawText = "tea 12.34",
                    confidence = 0.9,
                ),
            ),
        )

    private fun splitReplaceRequest(): ExpenseSplitReplaceRequestDto =
        ExpenseSplitReplaceRequestDto(
            expectedRowVersion = 12L,
            splits = listOf(
                ExpenseSplitRequestDto(
                    memberId = 7L,
                    amountCents = 1234L,
                    note = "share",
                ),
            ),
        )

    private fun categoryRuleUpdateRequest(): CategoryRuleUpdateRequest =
        CategoryRuleUpdateRequest(
            expectedRowVersion = 12L,
            keyword = "tea",
            category = "food",
            enabled = true,
            priority = 1,
            amountMinCents = 100L,
            amountMaxCents = 2000L,
            sourceContains = "ocr",
            tagContains = "lunch",
        )
}
