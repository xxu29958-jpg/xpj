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
import com.ticketbox.domain.model.CurrencyDisplay
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
    onOpenBudget: () -> Unit,
) {
    val currencyDisplay = LocalCurrencyDisplay.current

    StatsInsightSurface {
        if (budget == null) {
            BudgetEmptySection(onOpenBudget = onOpenBudget)
        } else {
            BudgetProgressSection(budget, currencyDisplay)
        }
    }
}

@Composable
private fun BudgetEmptySection(
    onOpenBudget: () -> Unit,
) {
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
                    text = stringResource(R.string.stats_budget_empty_status),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.labelSmall,
                )
            }
            Text(
                text = stringResource(R.string.stats_budget_empty_badge),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.labelMedium,
                maxLines = 1,
            )
        }
        Text(
            text = stringResource(R.string.stats_budget_empty_body),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodyMedium,
        )
        AppPrimaryButton(
            text = stringResource(R.string.stats_budget_empty_action),
            icon = Icons.Filled.Tune,
            modifier = Modifier.fillMaxWidth(),
            onClick = onOpenBudget,
        )
    }
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

internal fun budgetSpentPercent(budget: BudgetProgress): Int {
    if (budget.budgetCents <= 0L) return (budget.progress.coerceIn(0f, 1f) * 100).toInt()
    return ((budget.spentCents * 100) / budget.budgetCents).toInt()
}
