package com.ticketbox.viewmodel

import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.BudgetProgressStatus
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceUntilIdle
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull

/** Read refusal retires displayed financial data; it does not rewrite the user's draft. */
@OptIn(ExperimentalCoroutinesApi::class)
class BudgetReadAccessTest {
    @Test fun permissionRefusalHidesBudgetButKeepsTheOriginalDraftAndOcc() = budgetTest {
        val repository = FakeBudgetActions(budget(month = "2026-09"))
        val model = BudgetViewModel(repository, initialMonth = "2026-09")
        advanceUntilIdle()
        assertNotNull(model.uiState.value.budget)
        model.updateTotalAmount("1250.25")
        val original = model.uiState.value.form
        repository.monthlyBudgetResponder = { Result.failure(refused()) }

        model.refresh()
        advanceUntilIdle()

        assertNull(model.uiState.value.budget, "An explicit refusal is not permission to keep showing the last read")
        assertNotNull(model.uiState.value.loadError)
        assertEquals(original, model.uiState.value.form)
        assertEquals(true, model.uiState.value.formDirty)
        assertEquals("2026-09", model.uiState.value.month)
    }

    @Test fun permissionRefusalAlsoRetiresTheInsightsBudgetCard() = budgetTest {
        val repository = FakeBudgetActions(budget(month = "2026-09"))
        val model = StatsBudgetViewModel(repository)
        advanceUntilIdle()
        model.refresh("2026-09")
        advanceUntilIdle()
        assertNotNull(model.uiState.value.budgetProgress)
        repository.monthlyBudgetResponder = { Result.failure(refused()) }

        model.refresh("2026-09", force = true)
        advanceUntilIdle()

        assertNull(model.uiState.value.budgetProgress)
        assertEquals(BudgetProgressStatus.Unknown, model.uiState.value.budgetProgressStatus)
        assertEquals("2026-09", model.uiState.value.month)
    }

    private fun refused() = RepositoryException("Synthetic read refusal", errorCode = "permission_denied", httpStatusCode = 403)
}
