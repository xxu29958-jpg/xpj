package com.ticketbox.ui.screens

import com.ticketbox.domain.model.UiText
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtCounterpartyTypes
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.domain.model.DebtLinkStatuses
import com.ticketbox.domain.model.DebtRepaymentFactStatuses
import com.ticketbox.domain.model.DebtRepaymentHistory
import com.ticketbox.domain.model.DebtRepaymentRecord
import com.ticketbox.domain.model.DebtRepaymentVoidFact
import com.ticketbox.domain.model.DebtSourceTypes
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class DebtDetailScreenModelsTest {

    @Test
    fun bodyStateKeepsContentFirstAndSplitsNoDataLoadingFromFailure() {
        val error = UiText.raw("offline")

        assertEquals(
            DebtDetailBodyState.Content,
            debtDetailBodyState(hasDebt = true, isLoading = true, error = error),
        )
        assertEquals(
            DebtDetailBodyState.Loading,
            debtDetailBodyState(hasDebt = false, isLoading = true, error = error),
        )
        assertEquals(
            DebtDetailBodyState.LoadFailed,
            debtDetailBodyState(hasDebt = false, isLoading = false, error = error),
        )
        assertEquals(
            DebtDetailBodyState.Loading,
            debtDetailBodyState(hasDebt = false, isLoading = false, error = null),
        )
        assertEquals(error, debtDetailInlineMessage(DebtDetailBodyState.Content, error))
        assertNull(debtDetailInlineMessage(DebtDetailBodyState.LoadFailed, error))
    }

    @Test
    fun repaymentCorrectionRequiresFreshActiveCanonicalFactAndWritePermission() {
        val debt = externalDebt()
        val active = repaymentRecord()
        val history = repaymentHistory(debt.publicId, active)

        assertTrue(canVoidRepayment(debt, history, active, canModify = true, historyIsFresh = true))
        assertFalse(canVoidRepayment(debt, history, active, canModify = false, historyIsFresh = true))
        assertFalse(canVoidRepayment(debt, history, active, canModify = true, historyIsFresh = false))
        assertFalse(
            canVoidRepayment(
                debt.copy(status = DebtLinkStatuses.VOIDED),
                history,
                active,
                canModify = true,
                historyIsFresh = true,
            ),
        )
        assertFalse(canVoidRepayment(debt, repaymentHistory("other", active), active, true, true))
        val voided = active.copy(
            status = DebtRepaymentFactStatuses.VOIDED,
            voidFact = DebtRepaymentVoidFact("void-1", "重复记账", "2026-07-18T00:03:00Z"),
        )
        assertFalse(canVoidRepayment(debt, repaymentHistory(debt.publicId, voided), voided, true, true))
    }
}

private fun repaymentRecord(): DebtRepaymentRecord = DebtRepaymentRecord(
    publicId = "repayment-1",
    amountCents = 1_000L,
    originalCurrencyCode = null,
    originalAmountMinor = null,
    exchangeRateToCny = null,
    exchangeRateDate = null,
    exchangeRateSource = null,
    paidAt = "2026-07-18T00:00:00Z",
    createdAt = "2026-07-18T00:00:01Z",
    status = DebtRepaymentFactStatuses.ACTIVE,
    voidFact = null,
)

private fun repaymentHistory(
    debtPublicId: String,
    repayment: DebtRepaymentRecord,
): DebtRepaymentHistory = DebtRepaymentHistory(
    debtPublicId = debtPublicId,
    homeCurrencyCode = "CNY",
    items = listOf(repayment),
    page = 1,
    pageSize = 50,
    total = 1,
)

private fun externalDebt(): Debt = Debt(
    publicId = "d1",
    ledgerId = "owner",
    direction = DebtDirections.I_OWE,
    counterpartyType = DebtCounterpartyTypes.EXTERNAL,
    counterpartyAccountId = null,
    counterpartyLabel = "信用卡",
    principalAmountCents = 50_000L,
    remainingAmountCents = 40_000L,
    paidAmountCents = 10_000L,
    status = DebtLinkStatuses.OPEN,
    sourceType = DebtSourceTypes.MANUAL,
    sourceId = null,
    homeCurrencyCode = "CNY",
    originalCurrencyCode = null,
    originalAmountMinor = null,
    createdAt = "2026-07-18T00:00:00Z",
    updatedAt = "2026-07-18T00:01:00Z",
    rowVersion = 2L,
)
