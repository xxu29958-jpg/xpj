package com.ticketbox.data.repository

import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** 218-B4 review P2-19: the edit-completion advice invalidation hinges on
 *  [ExpenseDraft.changesAdvisorPayloadAgainst] — only payload-aggregated
 *  fields (amount / currency / category / captured date-time) may invalidate;
 *  note / tags / merchant / score edits must preserve the advice cache. */
class ExpenseAdvisorPayloadDiffTest {
    @Test
    fun noteTagMerchantOnlyEditIsNotPayloadRelevant() {
        val baseline = expense()
        val draft = ExpenseDraft(
            amountCents = baseline.amountCents,
            originalCurrencyCode = baseline.originalCurrencyCode,
            originalAmountMinor = baseline.originalAmountMinor,
            merchant = "新商家",
            category = baseline.category,
            note = "新备注",
            expenseTime = baseline.expenseTime,
            tags = "新标签",
            valueScore = null,
            regretScore = null,
        )

        assertFalse(draft.changesAdvisorPayloadAgainst(baseline))
    }

    @Test
    fun amountOrCurrencyEditIsPayloadRelevant() {
        val baseline = expense()

        // The amount axis is original-minor (mirrors toRequest's amountChanged):
        // editing only the CNY amountCents while originalAmountMinor is
        // unchanged is NOT a payload change.
        assertFalse(
            baseline.toDraft(amountCents = baseline.amountCents?.plus(100))
                .changesAdvisorPayloadAgainst(baseline),
        )
        assertTrue(
            baseline.toDraft(originalAmountMinor = 9900)
                .changesAdvisorPayloadAgainst(baseline),
        )
        assertTrue(
            baseline.toDraft(originalCurrencyCode = CurrencyCode.USD)
                .changesAdvisorPayloadAgainst(baseline),
        )
    }

    @Test
    fun categoryOrTimeEditIsPayloadRelevant() {
        val baseline = expense()

        assertTrue(
            baseline.toDraft(category = "餐饮")
                .changesAdvisorPayloadAgainst(baseline),
        )
        assertTrue(
            baseline.toDraft(expenseTime = "2026-05-02 08:30")
                .changesAdvisorPayloadAgainst(baseline),
        )
    }

    @Test
    fun pendingOrRejectedRowPayloadEditIsNotRelevant() {
        // The advisor aggregates the CONFIRMED set only — a payload-field edit
        // on a pending or rejected row changes nothing it reads (the later
        // confirm transition invalidates on its own always-true path).
        val pending = expense().copy(status = "pending", confirmedAt = null)
        val rejected = expense().copy(status = "rejected", confirmedAt = null)

        assertFalse(
            pending.toDraft(originalAmountMinor = 9900)
                .changesAdvisorPayloadAgainst(pending),
        )
        assertFalse(
            rejected.toDraft(originalAmountMinor = 9900)
                .changesAdvisorPayloadAgainst(rejected),
        )
    }

    private fun Expense.toDraft(
        amountCents: Long? = this.amountCents,
        originalCurrencyCode: CurrencyCode? = this.originalCurrencyCode,
        originalAmountMinor: Long? = this.originalAmountMinor,
        category: String? = this.category,
        expenseTime: String? = this.expenseTime,
    ): ExpenseDraft = ExpenseDraft(
        amountCents = amountCents,
        originalCurrencyCode = originalCurrencyCode,
        originalAmountMinor = originalAmountMinor,
        merchant = merchant,
        category = category,
        note = note,
        expenseTime = expenseTime,
        tags = tags,
        valueScore = null,
        regretScore = null,
    )

    private fun expense(): Expense = Expense(
        id = 1,
        publicId = "pub-1",
        amountCents = 10000,
        originalCurrency = CurrencyCode.CNY,
        originalCurrencyCode = CurrencyCode.CNY,
        originalAmountMinor = 10000,
        merchant = "商家",
        category = "其他",
        note = "备注",
        source = "manual",
        imagePath = null,
        thumbnailPath = null,
        imageHash = null,
        rawText = null,
        confidence = null,
        duplicateStatus = "none",
        duplicateOfId = null,
        duplicateReason = null,
        tags = "标签",
        valueScore = null,
        regretScore = null,
        status = "confirmed",
        expenseTime = "2026-05-01 12:00",
        createdAt = "2026-05-01T00:00:00Z",
        updatedAt = "2026-05-01T00:00:00Z",
        rowVersion = 1L,
        confirmedAt = "2026-05-01T00:00:00Z",
        rejectedAt = null,
    )
}
