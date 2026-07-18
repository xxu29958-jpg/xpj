package com.ticketbox.notification.budget

import com.ticketbox.domain.model.CurrencyCode
import kotlin.test.Test
import kotlin.test.assertEquals

/**
 * [NotifierBudgetOverspendDispatcher]：金额格式化（本位币 [com.ticketbox.ui.components.formatAmount]，
 * 不散写 ÷100）+ sent-key 作通知覆盖 tag 透传 + outcome 透传。窄函数接缝注 lambda 直测，
 * 不构造需要 Context 的 notifier（本模块无 Robolectric）。
 */
class NotifierBudgetOverspendDispatcherTest {

    private fun decisionOf(overspentCents: Long) = BudgetOverspendDecision(
        key = "v1:budget:ledger-1:2026-06",
        ledgerId = "ledger-1",
        month = "2026-06",
        overspentCents = overspentCents,
        homeCurrency = CurrencyCode.JPY,
    )

    @Test
    fun formatsOverspendAsHomeCurrencyAndPassesSentKeyAsDedupeTag() {
        var capturedAmount: String? = null
        var capturedTag: String? = null
        val dispatcher = NotifierBudgetOverspendDispatcher { amount, tag ->
            capturedAmount = amount
            capturedTag = tag
            BudgetOverspendDispatchOutcome.SENT
        }
        val outcome = dispatcher.dispatch(decisionOf(overspentCents = 1_234_56L))
        assertEquals(BudgetOverspendDispatchOutcome.SENT, outcome)
        // Server-authoritative JPY has zero fractional digits; do not reinterpret as CNY cents.
        assertEquals("¥123,456", capturedAmount)
        assertEquals("v1:budget:ledger-1:2026-06", capturedTag)
    }

    @Test
    fun passesThroughSkippedOutcomeUnchanged() {
        val dispatcher = NotifierBudgetOverspendDispatcher { _, _ ->
            BudgetOverspendDispatchOutcome.SKIPPED_DISABLED
        }
        assertEquals(
            BudgetOverspendDispatchOutcome.SKIPPED_DISABLED,
            dispatcher.dispatch(decisionOf(overspentCents = 100L)),
        )
    }
}
