package com.ticketbox.ui.screens

import androidx.annotation.StringRes
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.DebtCounterpartyTypes
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.domain.model.DebtGoalEvaluationStates
import com.ticketbox.domain.model.DebtGoalLink
import com.ticketbox.domain.model.DebtLinkStatuses
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.StateTone
import com.ticketbox.viewmodel.DebtAction

/**
 * ADR-0049 §6 (slice 7): backend debt string values → localized labels + state tones.
 * Pure `@StringRes` mappers (testable, mirroring `expenseSourceLabelRes`); a degraded
 * fallback keeps an unknown backend value rendering rather than crashing.
 */
@StringRes
internal fun debtGoalEvaluationLabelRes(state: String): Int = when (state) {
    DebtGoalEvaluationStates.IN_PROGRESS -> R.string.debt_goal_state_in_progress
    DebtGoalEvaluationStates.ACHIEVED -> R.string.debt_goal_state_achieved
    DebtGoalEvaluationStates.NOT_EVALUABLE -> R.string.debt_goal_state_not_evaluable
    else -> R.string.debt_goal_state_in_progress
}

@StringRes
internal fun debtLinkStatusLabelRes(status: String): Int = when (status) {
    DebtLinkStatuses.OPEN -> R.string.debt_link_status_open
    DebtLinkStatuses.CLEARED -> R.string.debt_link_status_cleared
    DebtLinkStatuses.VOIDED -> R.string.debt_link_status_voided
    else -> R.string.debt_link_status_open
}

@StringRes
internal fun debtDirectionLabelRes(direction: String): Int = when (direction) {
    DebtDirections.I_OWE -> R.string.debt_direction_i_owe
    DebtDirections.OWED_TO_ME -> R.string.debt_direction_owed_to_me
    else -> R.string.debt_direction_i_owe
}

/** Counterparty display: the explicit label, else a type-based fallback. */
@StringRes
internal fun debtCounterpartyFallbackRes(counterpartyType: String): Int = when (counterpartyType) {
    DebtCounterpartyTypes.MEMBER -> R.string.debt_goal_counterparty_member
    else -> R.string.debt_goal_counterparty_external
}

/** ADR-0049 §3 (slice 8c) detail action panel/sheet title for a [DebtAction]. */
@StringRes
internal fun debtActionTitleRes(action: DebtAction): Int = when (action) {
    DebtAction.Repayment -> R.string.debt_action_repayment_title
    DebtAction.Adjustment -> R.string.debt_action_adjustment_title
    DebtAction.Void -> R.string.debt_action_void_title
}

/** Amount-field label for a [DebtAction] (adjustment is a signed delta, hence its own copy). */
@StringRes
internal fun debtActionAmountLabelRes(action: DebtAction): Int = when (action) {
    DebtAction.Adjustment -> R.string.debt_action_adjustment_amount_label
    else -> R.string.debt_action_amount_label
}

@Composable
internal fun debtGoalEvaluationTone(state: String): StateTone {
    val tokens = LocalStateTokens.current
    return when (state) {
        DebtGoalEvaluationStates.ACHIEVED -> tokens.success
        DebtGoalEvaluationStates.NOT_EVALUABLE -> tokens.warn
        else -> tokens.info
    }
}

@Composable
internal fun debtLinkStatusTone(status: String): StateTone {
    val tokens = LocalStateTokens.current
    return when (status) {
        DebtLinkStatuses.CLEARED -> tokens.success
        DebtLinkStatuses.VOIDED -> tokens.danger
        else -> tokens.neutral
    }
}

@Composable
internal fun DebtStatusBadge(text: String, tone: StateTone) {
    Surface(
        color = tone.bg,
        contentColor = tone.fg,
        shape = MaterialTheme.shapes.small,
        border = BorderStroke(1.dp, tone.border),
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.labelSmall,
            modifier = Modifier.padding(
                horizontal = AppSpacing.smallGap,
                vertical = AppSpacing.miniGap,
            ),
        )
    }
}

/** A linked Debt's display counterparty — the label when present, else a type fallback. */
@Composable
internal fun debtLinkCounterparty(link: DebtGoalLink): String =
    link.counterpartyLabel?.takeIf { it.isNotBlank() }
        ?: stringResource(debtCounterpartyFallbackRes(link.counterpartyType))
