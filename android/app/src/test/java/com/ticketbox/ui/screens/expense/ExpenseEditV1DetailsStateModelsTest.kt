package com.ticketbox.ui.screens.expense

import com.ticketbox.viewmodel.ExpenseDetailDataLoadState
import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

internal class ExpenseEditV1DetailsStateModelsTest {

    @Test
    fun detailPanelPresentationOnlyTreatsLoadedModelsAsEmptyOrEditable() {
        listOf(
            ExpenseDetailDataLoadState.Unknown,
            ExpenseDetailDataLoadState.Loading,
            ExpenseDetailDataLoadState.Failed,
        ).forEach { loadState ->
            val presentation = expenseDetailPanelPresentation(
                loading = false,
                loadState = loadState,
                hasLoadedModel = false,
                hasRows = false,
                actionAvailable = true,
            )

            assertTrue(presentation.hasStateData, "loadState=$loadState must not show empty")
            assertFalse(presentation.showAction, "loadState=$loadState must not expose add/edit")
            assertFalse(presentation.showAuthoritativeTotal, "loadState=$loadState must not show a total")
        }

        val loadingLoadedModel = expenseDetailPanelPresentation(
            loading = true,
            loadState = ExpenseDetailDataLoadState.Loaded,
            hasLoadedModel = true,
            hasRows = false,
            actionAvailable = true,
        )
        assertTrue(loadingLoadedModel.showLoading)
        assertFalse(loadingLoadedModel.showAction)

        val loadedEmpty = expenseDetailPanelPresentation(
            loading = false,
            loadState = ExpenseDetailDataLoadState.Loaded,
            hasLoadedModel = true,
            hasRows = false,
            actionAvailable = true,
        )
        assertFalse(loadedEmpty.hasStateData)
        assertTrue(loadedEmpty.showAction)
        assertTrue(loadedEmpty.showAuthoritativeTotal)

        val loadedRows = expenseDetailPanelPresentation(
            loading = false,
            loadState = ExpenseDetailDataLoadState.Loaded,
            hasLoadedModel = true,
            hasRows = true,
            actionAvailable = true,
        )
        assertTrue(loadedRows.hasStateData)
        assertTrue(loadedRows.showAction)
        assertTrue(loadedRows.showAuthoritativeTotal)

        val loadedWithoutModel = expenseDetailPanelPresentation(
            loading = false,
            loadState = ExpenseDetailDataLoadState.Loaded,
            hasLoadedModel = false,
            hasRows = false,
            actionAvailable = true,
        )
        assertTrue(loadedWithoutModel.hasStateData)
        assertFalse(loadedWithoutModel.showAction)
        assertFalse(loadedWithoutModel.showAuthoritativeTotal)
    }
}
