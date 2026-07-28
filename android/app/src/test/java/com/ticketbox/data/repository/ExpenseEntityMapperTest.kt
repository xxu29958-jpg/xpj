package com.ticketbox.data.repository

import com.ticketbox.data.local.ExpenseEntity
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.ui.components.formatExpensePrimaryAmount
import kotlin.test.Test
import kotlin.test.assertEquals

class ExpenseEntityMapperTest {
    @Test
    fun confirmedRoomEntityDisplaysLedgerDataWithoutOriginalImage() {
        val expense = ExpenseEntity(
            ledgerId = "owner",
            serverId = 9,
            publicId = "691da31d-e8d7-49b0-bece-ec6f61c044b2",
            amountCents = 3680,
            merchant = "美团外卖",
            category = "餐饮",
            note = "午饭",
            source = "iPhone截图",
            thumbnailPath = null,
            imageHash = "hash",
            rawText = null,
            duplicateStatus = "none",
            duplicateOfId = null,
            duplicateReason = null,
            tags = null,
            valueScore = null,
            regretScore = null,
            status = "confirmed",
            expenseTime = "2026-05-04T04:20:00Z",
            createdAt = "2026-05-04T04:00:00Z",
            confirmedAt = "2026-05-04T04:30:00Z",
            updatedAt = "2026-05-04T04:30:00Z",
            rowVersion = 1L,
        ).toDomain()

        assertEquals(9, expense.id)
        assertEquals("confirmed", expense.status)
        assertEquals(3680, expense.amountCents)
        assertEquals("美团外卖", expense.merchant)
        assertEquals("餐饮", expense.category)
        assertEquals(null, expense.imagePath)
    }

    @Test
    fun optimisticCreateEntityStampsConfirmedLedgerCurrency() {
        // PR#255 R15b-1：JPY 安装离线手记乐观行 —— homeCurrencyCode 取提交时 VM 确认的
        // 账本币种（旧码恒 CNY 显示 ¥12.00），同币手记原值即 home（1200 minor → ¥1,200，
        // 与同步后权威行同口径）。
        val draft = optimisticDraft(
            originalCurrencyCode = CurrencyCode.JPY,
            originalAmountMinor = 1_200L,
            ledgerHomeCurrency = CurrencyCode.JPY,
        )
        val entity = draft.toLocalCreateEntity(ledgerId = "owner", clientRef = "ref-jpy")

        assertEquals("JPY", entity.homeCurrencyCode)
        assertEquals(1_200L, entity.amountCents)
        assertEquals("JPY", entity.originalCurrencyCode)
        assertEquals(1_200L, entity.originalAmountMinor)
        assertEquals("¥1,200", formatExpensePrimaryAmount(entity.copy(id = 1L).toDomain()))
    }

    @Test
    fun optimisticCreateEntityWithUnconvertibleOriginalKeepsOriginalLegOnly() {
        // PR#255 R15b-1：跨币不可折算（USD original + JPY home）→ home 置空不冒充
        // （旧码把 original minor 当 home 值），显示走 original 腿、聚合跳过（null）。
        val draft = optimisticDraft(
            originalCurrencyCode = CurrencyCode.USD,
            originalAmountMinor = 1_250L,
            ledgerHomeCurrency = CurrencyCode.JPY,
        )
        val entity = draft.toLocalCreateEntity(ledgerId = "owner", clientRef = "ref-fx")

        assertEquals("JPY", entity.homeCurrencyCode)
        assertEquals(null, entity.amountCents)
        assertEquals("USD", entity.originalCurrencyCode)
        assertEquals(1_250L, entity.originalAmountMinor)
        assertEquals("$12.50", formatExpensePrimaryAmount(entity.copy(id = 1L).toDomain()))
    }
}

private fun optimisticDraft(
    originalCurrencyCode: CurrencyCode,
    originalAmountMinor: Long,
    ledgerHomeCurrency: CurrencyCode,
): ExpenseDraft = ExpenseDraft(
    amountCents = null,
    originalCurrencyCode = originalCurrencyCode,
    originalAmountMinor = originalAmountMinor,
    merchant = "手动店",
    category = "餐饮",
    note = null,
    expenseTime = "2026-05-04T04:20:00Z",
    tags = null,
    valueScore = null,
    regretScore = null,
    ledgerHomeCurrency = ledgerHomeCurrency,
)
