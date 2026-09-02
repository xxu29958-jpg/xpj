package com.ticketbox.ui.screens.expense.fact

import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseFactBundle
import com.ticketbox.domain.model.ExpenseFinancialSummary
import com.ticketbox.domain.model.ExpenseLineageStatus
import com.ticketbox.domain.model.ExpenseRelationshipImpacts
import com.ticketbox.domain.model.ExpenseSourceValues
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * W2-B 详情金额呈现合同（与 Codex 共同冻结，三点一组）：
 * 1. 有已知 bundle 且 lineage 非 Confirmed → hero 稳定展示 server-owned 净额；
 *    query 刷新中/失败不摘已知投影（新鲜度由段内 stale/failed 文案表达）。
 *    command eligibility 的 Loaded 纪律不借用给展示。
 * 2. 净额 hero 伴生行 = 原始口径金额（· 已退回），original 币种 display。
 * 3. 普通外币账单（无净额但有原币金额且原币≠home）→ hero 下保留原币伴生行，
 *    原币事实不得从详情消失；客户端不做换算。
 */
class FactHeroTest {

    @Test
    fun knownActiveLineageKeepsNetHero() {
        assertTrue(factHeroShowsNet(bundleOf(ExpenseLineageStatus.PartiallyRefunded)))
        assertTrue(factHeroShowsNet(bundleOf(ExpenseLineageStatus.FullyRefunded)))
        assertTrue(factHeroShowsNet(bundleOf(ExpenseLineageStatus.Reversed)))
    }

    @Test
    fun confirmedOrUnknownBundleKeepsOriginalHero() {
        assertFalse(factHeroShowsNet(bundleOf(ExpenseLineageStatus.Confirmed)))
        assertFalse(factHeroShowsNet(null))
    }

    @Test
    fun foreignCurrencyBillKeepsOriginalCaption() {
        val usdBill = expense().copy(
            originalAmountMinor = 1000L,
            originalCurrencyCodeRaw = "USD",
            homeCurrencyCode = "CNY",
        )
        assertTrue(factHeroShowsOriginal(usdBill, showsNet = false))
    }

    @Test
    fun homeCurrencyBillHasNoRedundantCaption() {
        val cnyBill = expense().copy(originalAmountMinor = 26800L)
        assertFalse(factHeroShowsOriginal(cnyBill, showsNet = false))
    }

    @Test
    fun missingOriginalAmountHasNoCaption() {
        assertFalse(factHeroShowsOriginal(expense(), showsNet = false))
    }

    @Test
    fun unknownBundleLabelsGrossAmount() {
        assertEquals(FactHeroCaption.Gross, factHeroCaptionKind(expense(), bundle = null))
    }

    @Test
    fun unknownBundleForeignBillLabelsGrossAndOriginal() {
        val usdBill = expense().copy(
            originalAmountMinor = 1000L,
            originalCurrencyCodeRaw = "USD",
            homeCurrencyCode = "CNY",
        )
        assertEquals(FactHeroCaption.GrossOriginal, factHeroCaptionKind(usdBill, bundle = null))
    }

    @Test
    fun knownConfirmedBundleKeepsCleanHero() {
        assertEquals(
            FactHeroCaption.None,
            factHeroCaptionKind(expense(), bundleOf(ExpenseLineageStatus.Confirmed)),
        )
        val usdBill = expense().copy(
            originalAmountMinor = 1000L,
            originalCurrencyCodeRaw = "USD",
            homeCurrencyCode = "CNY",
        )
        assertEquals(
            FactHeroCaption.Original,
            factHeroCaptionKind(usdBill, bundleOf(ExpenseLineageStatus.Confirmed)),
        )
    }

    @Test
    fun activeLineageAlwaysNetCaption() {
        assertEquals(
            FactHeroCaption.Net,
            factHeroCaptionKind(expense(), bundleOf(ExpenseLineageStatus.PartiallyRefunded)),
        )
    }

    private fun expense(): Expense = Expense(
        id = 1L,
        publicId = "fact-hero-1",
        amountCents = 26800L,
        merchant = "MUJI 无印良品",
        category = "购物",
        note = null,
        source = ExpenseSourceValues.MANUAL_ENTRY,
        imagePath = null,
        thumbnailPath = null,
        imageHash = null,
        rawText = null,
        confidence = null,
        duplicateStatus = "",
        duplicateOfId = null,
        duplicateReason = null,
        tags = null,
        valueScore = null,
        regretScore = null,
        status = "confirmed",
        expenseTime = "2026-09-02T06:15:00Z",
        createdAt = "2026-09-02T16:52:00Z",
        updatedAt = "2026-09-02T16:52:00Z",
        rowVersion = 1L,
        confirmedAt = "2026-09-02T16:52:00Z",
        rejectedAt = null,
    )

    private fun bundleOf(status: ExpenseLineageStatus): ExpenseFactBundle {
        val root = expense()
        return ExpenseFactBundle(
            root = root,
            financialSummary = ExpenseFinancialSummary(
                grossOriginalMinor = 26800L,
                grossHomeAmountCents = 26800L,
                rootStreamAmountCents = 26800L,
                activeRefundedOriginalMinor = 9800L,
                remainingRefundableOriginalMinor = 17000L,
                lineageHomeNetCents = 17000L,
                fxDifferenceCents = 0L,
                status = status,
            ),
            activeOffsets = emptyList(),
            recentHistory = emptyList(),
            relationshipImpacts = ExpenseRelationshipImpacts(
                pendingInvitesCancelled = emptyList(),
                acceptedImpacts = emptyList(),
            ),
        )
    }
}
