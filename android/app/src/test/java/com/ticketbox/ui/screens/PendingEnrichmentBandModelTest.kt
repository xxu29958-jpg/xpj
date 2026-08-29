package com.ticketbox.ui.screens.pending

import com.ticketbox.R
import com.ticketbox.viewmodel.PendingEnrichmentFeedback
import com.ticketbox.viewmodel.PendingEnrichmentFeedbackKind
import com.ticketbox.viewmodel.PendingEnrichmentUiState
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class PendingEnrichmentBandModelTest {

    private fun feedback(kind: PendingEnrichmentFeedbackKind) = PendingEnrichmentFeedback(
        expenseId = 7L,
        kind = kind,
    )

    @Test
    fun idleStateHidesBand() {
        assertNull(
            pendingEnrichmentBandModel(
                state = PendingEnrichmentUiState(activeCount = 0, feedback = null),
                feedbackTargetPresent = false,
            ),
        )
    }

    @Test
    fun activeOnlyShowsCountAndAutoUpdateHint() {
        val model = pendingEnrichmentBandModel(
            state = PendingEnrichmentUiState(activeCount = 3, feedback = null),
            feedbackTargetPresent = false,
        )!!
        assertEquals(PendingEnrichmentBandTone.Info, model.tone)
        assertEquals(R.string.pending_enrichment_active, model.titleRes)
        assertEquals(3, model.titleArg)
        assertEquals(R.string.pending_enrichment_active_hint, model.detailRes)
        assertNull(model.action)
    }

    @Test
    fun terminalFeedbackKeepsActiveCountInDetailLine() {
        val model = pendingEnrichmentBandModel(
            state = PendingEnrichmentUiState(activeCount = 2, feedback = feedback(PendingEnrichmentFeedbackKind.Updated)),
            feedbackTargetPresent = true,
        )!!
        assertEquals(R.string.pending_enrichment_updated, model.titleRes)
        assertEquals(R.string.pending_enrichment_active_more, model.detailRes)
        assertEquals(2, model.detailArg)
    }

    @Test
    fun openExpenseActionOnlyWhenTargetStillInQueue() {
        val actionable = listOf(
            PendingEnrichmentFeedbackKind.Updated to R.string.pending_enrichment_action_review,
            PendingEnrichmentFeedbackKind.NoResult to R.string.pending_enrichment_action_complete,
            PendingEnrichmentFeedbackKind.Conflict to R.string.pending_enrichment_action_view,
            PendingEnrichmentFeedbackKind.Failed to R.string.pending_enrichment_action_open,
        )
        for ((kind, labelRes) in actionable) {
            val present = pendingEnrichmentBandModel(
                state = PendingEnrichmentUiState(feedback = feedback(kind)),
                feedbackTargetPresent = true,
            )!!
            assertEquals(PendingEnrichmentBandAction.OpenExpense, present.action, kind.name)
            assertEquals(labelRes, present.actionLabelRes, kind.name)

            val gone = pendingEnrichmentBandModel(
                state = PendingEnrichmentUiState(feedback = feedback(kind)),
                feedbackTargetPresent = false,
            )!!
            assertNull(gone.action, kind.name)
            assertNull(gone.actionLabelRes, kind.name)
        }
    }

    @Test
    fun lightKindsHaveNoAction() {
        for (kind in listOf(PendingEnrichmentFeedbackKind.Cancelled, PendingEnrichmentFeedbackKind.NotPending)) {
            val model = pendingEnrichmentBandModel(
                state = PendingEnrichmentUiState(feedback = feedback(kind)),
                feedbackTargetPresent = true,
            )!!
            assertEquals(PendingEnrichmentBandTone.Neutral, model.tone, kind.name)
            assertNull(model.action, kind.name)
        }
    }

    @Test
    fun unavailableAlwaysOffersRetryCheckNotReOcr() {
        val model = pendingEnrichmentBandModel(
            state = PendingEnrichmentUiState(feedback = feedback(PendingEnrichmentFeedbackKind.Unavailable)),
            feedbackTargetPresent = false,
        )!!
        assertEquals(PendingEnrichmentBandTone.Warn, model.tone)
        assertEquals(R.string.pending_enrichment_unavailable, model.titleRes)
        assertEquals(PendingEnrichmentBandAction.RetryObservation, model.action)
        assertEquals(R.string.pending_enrichment_action_retry_check, model.actionLabelRes)
    }

    @Test
    fun toneHierarchyMatchesWebBand() {
        assertEquals(
            PendingEnrichmentBandTone.Success,
            pendingEnrichmentBandModel(
                PendingEnrichmentUiState(feedback = feedback(PendingEnrichmentFeedbackKind.Updated)),
                feedbackTargetPresent = false,
            )!!.tone,
        )
        assertEquals(
            PendingEnrichmentBandTone.Warn,
            pendingEnrichmentBandModel(
                PendingEnrichmentUiState(feedback = feedback(PendingEnrichmentFeedbackKind.NoResult)),
                feedbackTargetPresent = false,
            )!!.tone,
        )
        assertEquals(
            PendingEnrichmentBandTone.Danger,
            pendingEnrichmentBandModel(
                PendingEnrichmentUiState(feedback = feedback(PendingEnrichmentFeedbackKind.Failed)),
                feedbackTargetPresent = false,
            )!!.tone,
        )
        assertEquals(
            PendingEnrichmentBandTone.Info,
            pendingEnrichmentBandModel(
                PendingEnrichmentUiState(feedback = feedback(PendingEnrichmentFeedbackKind.Conflict)),
                feedbackTargetPresent = false,
            )!!.tone,
        )
    }
}
