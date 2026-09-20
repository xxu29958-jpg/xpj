package com.ticketbox.ui.screens

import com.ticketbox.data.repository.toDomain

import com.ticketbox.domain.model.UiText
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class DebtDetailScreenModelsTest {
    @Test fun splitCelebrationRequiresCurrentRelationshipSettlementAndMatchingBinding() {
        val agreement = com.ticketbox.data.repository.splitTestAgreement().copy(settlementNetAmountCents = 0)
        val binding = com.ticketbox.data.repository.LogicalSessionBinding("https://example.test", "ledger", "owner", "session", "revision")
        val state = com.ticketbox.viewmodel.SplitAgreementUiState(
            task = com.ticketbox.data.repository.DebtTask(binding, "original"), agreement = agreement)
        val debt = agreement.originalDebt.toDomain()
        kotlin.test.assertTrue(splitRelationSettled(debt, binding, state))
        kotlin.test.assertFalse(splitRelationSettled(debt.copy(rowVersion = 8), binding, state))
        kotlin.test.assertFalse(splitRelationSettled(debt, binding.copy(bindingRevision = "new"), state))
        kotlin.test.assertFalse(splitRelationSettled(debt, binding, state.copy(agreement = agreement.copy(settlementNetAmountCents = -1000))))
    }


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
}
