package com.ticketbox.ui.screens

import com.ticketbox.domain.model.UiText
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

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
}
