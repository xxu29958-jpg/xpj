package com.ticketbox.ui.screens

import com.ticketbox.R
import kotlin.test.Test
import kotlin.test.assertEquals

/**
 * ADR-0049 §6 (slice 7): the pure `@StringRes` label mappers. An unknown backend
 * value must degrade to a sensible default rather than crash (mirrors
 * `expenseSourceLabelRes`'s else branch).
 */
class DebtGoalLabelsTest {

    @Test
    fun evaluationStateLabelsMapKnownValuesAndDegrade() {
        assertEquals(R.string.debt_goal_state_in_progress, debtGoalEvaluationLabelRes("in_progress"))
        assertEquals(R.string.debt_goal_state_achieved, debtGoalEvaluationLabelRes("achieved"))
        assertEquals(R.string.debt_goal_state_not_evaluable, debtGoalEvaluationLabelRes("not_evaluable"))
        assertEquals(R.string.debt_goal_state_in_progress, debtGoalEvaluationLabelRes("future_state"))
    }

    @Test
    fun linkStatusLabelsMapKnownValuesAndDegrade() {
        assertEquals(R.string.debt_link_status_open, debtLinkStatusLabelRes("open"))
        assertEquals(R.string.debt_link_status_cleared, debtLinkStatusLabelRes("cleared"))
        assertEquals(R.string.debt_link_status_voided, debtLinkStatusLabelRes("voided"))
        assertEquals(R.string.debt_link_status_open, debtLinkStatusLabelRes("future_status"))
    }

    @Test
    fun directionLabelsMapKnownValuesAndDegrade() {
        assertEquals(R.string.debt_direction_i_owe, debtDirectionLabelRes("i_owe"))
        assertEquals(R.string.debt_direction_owed_to_me, debtDirectionLabelRes("owed_to_me"))
        assertEquals(R.string.debt_direction_i_owe, debtDirectionLabelRes("future_direction"))
    }

    @Test
    fun counterpartyFallbackMapsTypeToLabel() {
        assertEquals(R.string.debt_goal_counterparty_member, debtCounterpartyFallbackRes("member"))
        assertEquals(R.string.debt_goal_counterparty_external, debtCounterpartyFallbackRes("external"))
        // unknown counterparty type falls back to the external label.
        assertEquals(R.string.debt_goal_counterparty_external, debtCounterpartyFallbackRes("future_type"))
    }
}
