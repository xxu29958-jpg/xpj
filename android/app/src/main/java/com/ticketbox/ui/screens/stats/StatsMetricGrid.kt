package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.BudgetProgress
import com.ticketbox.domain.model.BudgetProgressStatus
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.moneyPercent
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.LocalThemeVisuals

@Composable
internal fun StatsMetricGrid(
    budget: BudgetProgress?,
    budgetStatus: BudgetProgressStatus,
    onOpenBudget: () -> Unit,
) {
    val currencyDisplay = LocalCurrencyDisplay.current

    StatsInsightSurface {
        if (budget != null) {
            BudgetProgressSection(budget, currencyDisplay)
        } else {
            BudgetStatusSection(
                budgetStatus = budgetStatus,
                onOpenBudget = onOpenBudget,
            )
        }
    }
}

@Composable
private fun BudgetStatusSection(
    budgetStatus: BudgetProgressStatus,
    onOpenBudget: () -> Unit,
) {
    val copy = budgetStatusCopy(budgetStatus)
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
                Text(
                    text = stringResource(R.string.stats_budget_progress_title),
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = AppTextHierarchy.heading.weight,
                )
                Text(
                    text = stringResource(copy.status),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.labelSmall,
                )
            }
            Text(
                text = stringResource(copy.badge),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.labelMedium,
                maxLines = 1,
            )
        }
        Text(
            text = stringResource(copy.body),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodyMedium,
        )
        AppPrimaryButton(
            text = stringResource(copy.action),
            icon = Icons.Filled.Tune,
            modifier = Modifier.fillMaxWidth(),
            onClick = onOpenBudget,
        )
    }
}

private data class BudgetStatusCopy(
    val status: Int,
    val badge: Int,
    val body: Int,
    val action: Int,
)

private fun budgetStatusCopy(budgetStatus: BudgetProgressStatus): BudgetStatusCopy =
    when (budgetStatus) {
        BudgetProgressStatus.ConfiguredWithoutProgress -> BudgetStatusCopy(
            status = R.string.stats_budget_progress_unavailable_status,
            badge = R.string.stats_budget_progress_configured,
            body = R.string.stats_budget_progress_unavailable_body,
            action = R.string.stats_budget_open_action,
        )
        BudgetProgressStatus.Unknown -> BudgetStatusCopy(
            status = R.string.stats_budget_unknown_status,
            badge = R.string.stats_budget_unknown_badge,
            body = R.string.stats_budget_unknown_body,
            action = R.string.stats_budget_open_action,
        )
        BudgetProgressStatus.Progress -> BudgetStatusCopy(
            status = R.string.stats_budget_progress_configured,
            badge = R.string.stats_budget_progress_configured,
            body = R.string.stats_budget_progress_hint,
            action = R.string.stats_budget_open_action,
        )
        BudgetProgressStatus.Unconfigured -> BudgetStatusCopy(
            status = R.string.stats_budget_empty_status,
            badge = R.string.stats_budget_empty_badge,
            body = R.string.stats_budget_empty_body,
            action = R.string.stats_budget_empty_action,
        )
    }

@Composable
private fun BudgetProgressSection(
    budget: BudgetProgress,
    currencyDisplay: CurrencyDisplay,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
                Text(
                    stringResource(R.string.stats_budget_progress_title),
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = AppTextHierarchy.heading.weight,
                )
                Text(
                    text = stringResource(R.string.stats_budget_progress_configured),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    text = if (budget.overBudget) {
                        stringResource(R.string.stats_budget_progress_over)
                    } else {
                        stringResource(
                            R.string.stats_budget_progress_remaining,
                            formatDisplayAmount(budget.remainingCents, currencyDisplay),
                        )
                    },
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = AppTextHierarchy.heading.weight,
                )
            }
            Text(
                text = stringResource(R.string.stats_budget_progress_percent, budgetSpentPercent(budget)),
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                fontWeight = AppTextHierarchy.body.weight,
            )
        }
        BudgetBulletBar(budget)
        Text(
            text = stringResource(R.string.stats_budget_progress_hint),
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun BudgetBulletBar(budget: BudgetProgress) {
    val visuals = LocalThemeVisuals.current
    val tick = budgetTickFraction(budget)
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(7.dp)
            .clip(RoundedCornerShape(AppRadius.pill))
            .background(MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = AppAlpha.faint)),
    ) {
        if (tick == null) {
            Box(
                modifier = Modifier
                    .fillMaxWidth(budget.progress.coerceIn(0f, 1f))
                    .height(7.dp)
                    .clip(RoundedCornerShape(AppRadius.pill))
                    .background(visuals.primary),
            )
        } else {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(7.dp)
                    .background(visuals.warningTint),
            )
            Box(
                modifier = Modifier
                    .fillMaxWidth(tick)
                    .height(7.dp)
                    .background(visuals.primary),
            )
            Row(modifier = Modifier.fillMaxWidth()) {
                if (tick > 0f) {
                    Box(modifier = Modifier.weight(tick))
                }
                Box(
                    modifier = Modifier
                        .width(2.dp)
                        .height(7.dp)
                        .background(MaterialTheme.colorScheme.onSurface),
                )
                if (tick < 1f) {
                    Box(modifier = Modifier.weight(1f - tick))
                }
            }
        }
    }
}

internal fun budgetTickFraction(budget: BudgetProgress): Float? {
    if (!budget.overBudget) return null
    if (budget.budgetCents <= 0L || budget.spentCents <= 0L) return null
    if (budget.spentCents <= budget.budgetCents) return null
    return (budget.budgetCents.toFloat() / budget.spentCents.toFloat()).coerceIn(0f, 1f)
}

internal fun budgetSpentPercent(budget: BudgetProgress): Long =
    moneyPercent(budget.spentCents, budget.budgetCents)
        ?: (budget.progress.coerceIn(0f, 1f) * 100).toLong()
