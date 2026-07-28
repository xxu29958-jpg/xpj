package com.ticketbox.viewmodel

import com.ticketbox.data.repository.DebtListPage
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Debt
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

/** R14-6：共享账本币种同源裁决（自 DebtListViewModel 提升）的直接钉 —— 信任口径的
 *  六个分支一次钉死，三 VM 镜像点共用同一实现。 */
class LedgerCurrencyResolutionTest {

    @Test
    fun emptyLedgerFallsBackToEnvelopeCapability() {
        // 空账本无 record 权威 → capability 独立放行（首笔创建不破「等首条 record」循环）。
        assertEquals(
            CurrencyCode.JPY,
            resolveLedgerCurrency(DebtListPage(debts = emptyList(), ledgerHomeCurrencyCode = "JPY")),
        )
    }

    @Test
    fun nonEmptyLedgerTakesRecordAuthorityWhenCapabilityMissing() {
        // 旧服务端无信封字段（null）：record 码独立权威，不降级。
        assertEquals(
            CurrencyCode.JPY,
            resolveLedgerCurrency(
                DebtListPage(debts = listOf(resolutionDebt("JPY")), ledgerHomeCurrencyCode = null),
            ),
        )
    }

    @Test
    fun conflictingRecordAndCapabilityFailClosed() {
        // 两源在场却不一致 = binding 漂移 → fail closed，不猜任一侧。
        assertNull(
            resolveLedgerCurrency(
                DebtListPage(debts = listOf(resolutionDebt("CNY")), ledgerHomeCurrencyCode = "JPY"),
            ),
        )
    }

    @Test
    fun mixedRecordCodesFailClosed() {
        // >1 个已知 record 码 = 漂移后新旧 record 并存 → fail closed（不得落 capability 放行）。
        assertNull(
            resolveLedgerCurrency(
                DebtListPage(
                    debts = listOf(resolutionDebt("CNY"), resolutionDebt("JPY")),
                    ledgerHomeCurrencyCode = "CNY",
                ),
            ),
        )
    }

    @Test
    fun unknownRecordCodeFailsClosedEvenWithKnownCapability() {
        // 任一 record 未知键（支持集外）→ fail closed：按其口径解析会放大/缩小金额。
        assertNull(
            resolveLedgerCurrency(
                DebtListPage(debts = listOf(resolutionDebt("VND")), ledgerHomeCurrencyCode = "CNY"),
            ),
        )
    }

    @Test
    fun presentButUnknownCapabilityFailsClosed() {
        // R8-1：capability 非 blank 却在支持集外 ≠ 缺失 —— 即便 record 已知也 fail closed。
        assertNull(
            resolveLedgerCurrency(
                DebtListPage(debts = listOf(resolutionDebt("CNY")), ledgerHomeCurrencyCode = "VND"),
            ),
        )
        // 拉取失败（page=null）两源皆缺 → 同归 null。
        assertNull(resolveLedgerCurrency(null))
    }
}

private fun resolutionDebt(homeCurrencyCode: String): Debt = Debt(
    publicId = "debt-$homeCurrencyCode",
    ledgerId = "owner",
    direction = "i_owe",
    counterpartyType = "external",
    counterpartyAccountId = null,
    counterpartyLabel = "对手方",
    principalAmountCents = 100_000,
    remainingAmountCents = 40_000,
    paidAmountCents = 60_000,
    status = "open",
    sourceType = "manual",
    sourceId = null,
    homeCurrencyCode = homeCurrencyCode,
    originalCurrencyCode = null,
    originalAmountMinor = null,
    createdAt = "2026-06-13T00:00:00Z",
    updatedAt = "2026-06-15T00:00:00Z",
    rowVersion = 1L,
)
