package com.ticketbox.ui.screens.budget

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material.icons.outlined.ExpandMore
import androidx.compose.material.icons.outlined.ExpandLess
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.BudgetMonthly
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.components.AppSecondaryPageHeader
import com.ticketbox.ui.components.displayDateTime
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.LocalThemeVisuals

@Composable
internal fun BudgetCachedHeader(backText: String, onBack: (() -> Unit)?, onHistory: () -> Unit) {
    AppSecondaryPageHeader(
        title = stringResource(R.string.budget_read_cached_title),
        subtitle = stringResource(R.string.budget_cached_subtitle),
        backText = backText,
        onBack = onBack,
        actions = { TextButton(onClick = onHistory) { Text(stringResource(R.string.budget_history_title)) } },
    )
}

@Composable
internal fun BudgetCachedReadSource(fetchedAt: String) {
    val warning = LocalStateTokens.current.warn
    Surface(modifier = Modifier.fillMaxWidth().testTag("budget-read-source"),
        shape = RoundedCornerShape(AppRadius.large), color = warning.bg) {
        Row(Modifier.padding(AppSpacing.cardPaddingSmall), horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            Icon(Icons.Outlined.Info, contentDescription = null, tint = warning.fg,
                modifier = Modifier.size(AppSpacing.cardPadding))
            Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
                Text(stringResource(R.string.budget_cached_time, displayDateTime(fetchedAt)), color = warning.fg,
                    style = MaterialTheme.typography.bodyMedium, fontWeight = AppTextHierarchy.heading.weight)
                Text(stringResource(R.string.budget_cached_notice), color = warning.fg, style = MaterialTheme.typography.bodyMedium)
            }
        }
    }
}

@Composable
internal fun BudgetCachedSummary(budget: BudgetMonthly, currencyDisplay: CurrencyDisplay, details: @Composable () -> Unit) {
    var expanded by rememberSaveable(budget.ledgerId, budget.month) { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        Surface(onClick = { expanded = !expanded }, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(AppRadius.hero),
            color = LocalThemeVisuals.current.surfaceRaised) {
            Column(Modifier.padding(AppSpacing.screenHorizontal), verticalArrangement = Arrangement.spacedBy(AppSpacing.sectionGap)) {
                BudgetSummaryHero(budget, currencyDisplay, fromCache = true)
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
                    Text(stringResource(R.string.budget_cached_basis, budget.homeCurrencyCode ?: "UNKNOWN", budget.month),
                        modifier = Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text(stringResource(if (expanded) R.string.budget_cached_details_hide else R.string.budget_cached_details_show),
                        style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.primary)
                    Icon(if (expanded) Icons.Outlined.ExpandLess else Icons.Outlined.ExpandMore, contentDescription = null,
                        modifier = Modifier.size(AppSpacing.cardPadding), tint = MaterialTheme.colorScheme.primary)
                }
            }
        }
        if (expanded || budget.missingCurrencyCodes.isNotEmpty()) {
            Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) { details() }
        }
    }
}
