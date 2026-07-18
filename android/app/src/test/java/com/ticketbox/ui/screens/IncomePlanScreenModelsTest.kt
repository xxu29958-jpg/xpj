package com.ticketbox.ui.screens

import com.ticketbox.domain.model.UiText
import com.ticketbox.viewmodel.IncomePlanDraftUi
import com.ticketbox.viewmodel.IncomePlanLoadState
import com.ticketbox.viewmodel.IncomePlanUiState
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class IncomePlanScreenModelsTest {

    @Test
    fun bodyStateSeparatesLoadingFailureEmptyAndReadableRows() {
        val error = UiText.raw("failed")

        assertEquals(
            IncomePlanBodyState.Loading,
            incomePlanBodyState(IncomePlanLoadState.Unknown, activeCount = 0, archivedCount = 0),
        )
        assertEquals(
            IncomePlanBodyState.LoadFailed,
            incomePlanBodyState(IncomePlanLoadState.Failed, activeCount = 0, archivedCount = 0),
        )
        assertEquals(
            IncomePlanBodyState.Empty,
            incomePlanBodyState(IncomePlanLoadState.Loaded, activeCount = 0, archivedCount = 0),
        )
        assertEquals(
            IncomePlanBodyState.Content,
            incomePlanBodyState(IncomePlanLoadState.Failed, activeCount = 1, archivedCount = 0),
        )
        assertEquals(
            IncomePlanBodyState.Content,
            incomePlanBodyState(IncomePlanLoadState.Loading, activeCount = 0, archivedCount = 1),
        )
        assertNull(incomePlanInlineMessage(IncomePlanBodyState.LoadFailed, error))
        assertEquals(error, incomePlanInlineMessage(IncomePlanBodyState.Content, error))
        assertEquals(error, incomePlanInlineMessage(IncomePlanBodyState.Empty, error))
        assertTrue(incomePlanShowsSummary(IncomePlanBodyState.Empty))
        assertFalse(incomePlanShowsSummary(IncomePlanBodyState.Loading))
    }

    @Test
    fun addIncomeSaveRequiresNameAndAmountBeforeSubmit() {
        assertFalse(incomePlanSubmitEnabled(IncomePlanUiState()))
        assertFalse(
            incomePlanSubmitEnabled(
                IncomePlanUiState(addDraft = IncomePlanDraftUi(label = "工资")),
            ),
        )
        assertFalse(
            incomePlanSubmitEnabled(
                IncomePlanUiState(addDraft = IncomePlanDraftUi(amountYuanInput = "8000")),
            ),
        )
        assertTrue(
            incomePlanSubmitEnabled(
                IncomePlanUiState(
                    addDraft = IncomePlanDraftUi(
                        label = "工资",
                        amountYuanInput = "8000",
                    ),
                ),
            ),
        )
        assertFalse(
            incomePlanSubmitEnabled(
                IncomePlanUiState(
                    addDraft = IncomePlanDraftUi(
                        label = "工资",
                        amountYuanInput = "8000",
                    ),
                    isSubmitting = true,
                ),
            ),
        )
    }
}
