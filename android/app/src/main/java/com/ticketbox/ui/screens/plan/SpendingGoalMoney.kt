package com.ticketbox.ui.screens.plan

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.Goal
import com.ticketbox.ui.components.AppProgressBar
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.tabularNum

@Composable
internal fun spendingGoalAmountText(amount: Long?, currencyCode: String?): String {
    if (amount == null) return stringResource(R.string.spending_goal_amount_unavailable)
    val currency = CurrencyCode.fromStorageKeyOrNull(currencyCode)
    return when {
        currency != null -> "${currency.storageKey} ${formatDisplayAmount(amount, CurrencyDisplay(currency))}"
        currencyCode.isNullOrBlank() -> stringResource(R.string.spending_goal_original_amount_unknown, amount)
        else -> formatDisplayAmount(amount, CurrencyDisplay.forRecord(currencyCode))
    }
}

@Composable
internal fun SpendingGoalOriginalSummary(name: String?, month: String?, amount: Long?, currencyCode: String?) {
    name?.let { Text(it) }
    amount?.let { Text(stringResource(R.string.spending_goal_submission_amount, spendingGoalAmountText(it, currencyCode))) }
    month?.let { Text(stringResource(R.string.spending_goal_submission_month, it)) }
}

@Composable
internal fun SpendingGoalProgress(goal: Goal, showPercent: Boolean = false) {
    val progress = goal.progress
    if (progress == null) {
        Text(
            text = stringResource(R.string.spending_goal_progress_unavailable),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        return
    }
    if (showPercent) {
        Text(
            text = stringResource(R.string.spending_goal_progress_percent, requireNotNull(goal.progressPercent)),
            color = goal.stateTone().fg,
            style = MaterialTheme.typography.headlineMedium.tabularNum(),
            fontWeight = FontWeight.SemiBold,
        )
    }
    AppProgressBar(
        fraction = progress,
        tone = goal.stateTone(),
        height = AppSpacing.smallGap,
        contentDescription = stringResource(R.string.spending_goal_progress_a11y, goal.name, requireNotNull(goal.progressPercent)),
    )
}
