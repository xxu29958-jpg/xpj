package com.ticketbox.ui.screens

import com.ticketbox.R
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtCounterpartyTypes
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.domain.model.DebtLinkStatuses
import com.ticketbox.domain.model.DebtSourceTypes
import com.ticketbox.domain.model.UiText
import com.ticketbox.viewmodel.DebtListUiState
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class DebtListScreenModelsTest {

    @Test
    fun bodyStateSeparatesInitialLoadingFailureEmptyAndContent() {
        assertEquals(ReadableListBodyState.Loading, debtListBodyState(DebtListUiState(isLoading = true)))
        assertEquals(
            ReadableListBodyState.LoadFailed,
            debtListBodyState(DebtListUiState(error = loadFailed())),
        )
        assertEquals(ReadableListBodyState.Empty, debtListBodyState(DebtListUiState()))
        assertEquals(ReadableListBodyState.Content, debtListBodyState(DebtListUiState(debts = listOf(debt()))))
    }

    @Test
    fun inlineErrorOnlyAppearsWhenReadableDebtRowsRemain() {
        val error = loadFailed()

        assertNull(debtListInlineError(DebtListUiState(error = error)))
        assertEquals(error, debtListInlineError(DebtListUiState(debts = listOf(debt()), error = error)))
    }

    private fun loadFailed(): UiText = UiText.res(R.string.debt_list_load_failed)

    private fun debtListBodyState(state: DebtListUiState): ReadableListBodyState =
        readableListBodyState(
            hasRows = state.debts.isNotEmpty(),
            isLoading = state.isLoading,
            error = state.error,
        )

    private fun debtListInlineError(state: DebtListUiState): UiText? =
        readableListInlineError(hasRows = state.debts.isNotEmpty(), error = state.error)

    private fun debt(): Debt = Debt(
        publicId = "debt_1",
        ledgerId = "ledger_1",
        direction = DebtDirections.I_OWE,
        counterpartyType = DebtCounterpartyTypes.EXTERNAL,
        counterpartyAccountId = null,
        counterpartyLabel = "Counterparty",
        principalAmountCents = 10_000,
        remainingAmountCents = 6_000,
        paidAmountCents = 4_000,
        status = DebtLinkStatuses.OPEN,
        sourceType = DebtSourceTypes.MANUAL,
        sourceId = null,
        homeCurrencyCode = "CNY",
        originalCurrencyCode = null,
        originalAmountMinor = null,
        createdAt = "2026-07-01T00:00:00Z",
        updatedAt = "2026-07-01T00:00:00Z",
        rowVersion = 1,
    )
}
