package com.ticketbox.ui.screens

import com.ticketbox.R
import kotlin.test.Test
import kotlin.test.assertEquals

/**
 * ADR-0049 §6 (slice 7): the pure `@StringRes` label mappers. P4 (model-invariant
 * hardening): an unknown/future backend value must degrade to a NEUTRAL read-only 未知
 * label — never the optimistic actionable 进行中/未结清/应付 — so a server-added state is
 * not silently rendered as operable.
 */
class DebtGoalLabelsTest {

    @Test
    fun evaluationStateLabelsMapKnownValuesAndDegradeToUnknown() {
        assertEquals(R.string.debt_goal_state_in_progress, debtGoalEvaluationLabelRes("in_progress"))
        assertEquals(R.string.debt_goal_state_achieved, debtGoalEvaluationLabelRes("achieved"))
        assertEquals(R.string.debt_goal_state_not_evaluable, debtGoalEvaluationLabelRes("not_evaluable"))
        assertEquals(R.string.debt_goal_state_unknown, debtGoalEvaluationLabelRes("future_state"))
    }

    @Test
    fun linkStatusLabelsMapKnownValuesAndDegradeToUnknown() {
        assertEquals(R.string.debt_link_status_open, debtLinkStatusLabelRes("open"))
        assertEquals(R.string.debt_link_status_cleared, debtLinkStatusLabelRes("cleared"))
        assertEquals(R.string.debt_link_status_voided, debtLinkStatusLabelRes("voided"))
        assertEquals(R.string.debt_link_status_unknown, debtLinkStatusLabelRes("future_status"))
    }

    @Test
    fun directionLabelsMapKnownValuesAndDegradeToUnknown() {
        assertEquals(R.string.debt_direction_i_owe, debtDirectionLabelRes("i_owe"))
        assertEquals(R.string.debt_direction_owed_to_me, debtDirectionLabelRes("owed_to_me"))
        assertEquals(R.string.debt_direction_unknown, debtDirectionLabelRes("future_direction"))
    }

    @Test
    fun counterpartyFallbackMapsTypeToLabel() {
        assertEquals(R.string.debt_goal_counterparty_member, debtCounterpartyFallbackRes("member"))
        assertEquals(R.string.debt_goal_counterparty_external, debtCounterpartyFallbackRes("external"))
        // unknown counterparty type falls back to the external label.
        assertEquals(R.string.debt_goal_counterparty_external, debtCounterpartyFallbackRes("future_type"))
    }
}
