package com.ticketbox.data.repository

import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.RepaymentReviewInputEntity
import com.ticketbox.data.remote.dto.RepaymentDraftDto
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull

class RepaymentReviewCommandTest {
    @Test fun unchangedCapturedMoneyKeepsItsKnownHomeAmountWhileAnExplicitCorrectionTravelsSeparately() {
        val binding = LogicalSessionBinding("https://isolated.invalid", "ledger", "owner", "session", "binding")
        val adapters = OutboxAdapterGraph()
        val original = RepaymentDraftDto("capture-original", "alipay", 1400, "USD", "原银行卡", "2026-09-01T00:00:00Z",
            "pending", createdAt = "2026-09-01T00:00:01Z", originalCurrencyCode = "CNY", originalAmountMinor = 10000).toDomain()
        val input = reviewInput(binding)
        val unchanged = input.copy(amountText = "100.00").command(binding, original, false, adapters)
        val oldMoney = assertNotNull(adapters.repaymentReviewAdapter.fromJson(unchanged.payloadJson)).request
        assertEquals(null, oldMoney.originalCurrency)
        assertEquals(null, oldMoney.originalAmount)
        assertEquals(null, oldMoney.timeInput, "legacy input keeps captured time; no new date is fabricated")
        val changed = assertNotNull(adapters.repaymentReviewAdapter.fromJson(input.command(binding, original, false, adapters).payloadJson)).request
        assertEquals("90.00", changed.originalAmount)
        assertEquals(10000L, original.originalAmountMinor)
        assertEquals(1400L, original.amountCents)
    }
}

private fun reviewInput(binding: LogicalSessionBinding) = RepaymentReviewInputEntity(binding.ownerKey, binding.ledgerId,
    "capture-original", binding.serverUrl, binding.sessionGeneration, binding.bindingRevision, "original-review-key",
    "CNY", " 90.00 ", "debt-original", "原欠款", "USD", 7)
