package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyProjectionGap
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.StatsSource
import com.ticketbox.viewmodel.StatsUiState

@Composable
internal fun StatsProjectionNotice(state: StatsUiState, onRepair: (CurrencyProjectionGap) -> Unit) {
    val stats = state.stats ?: return
    val lifestyle = state.lifestyleStats?.takeIf { it.month == state.month && state.selectedTag.isBlank() }
    val gaps = (stats.missingRates + lifestyle?.missingRates.orEmpty()).distinct()
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        Text(stringResource(R.string.stats_projection_currency, stats.homeCurrencyCode), style = MaterialTheme.typography.bodySmall)
        if (state.statsSource == StatsSource.CachedSnapshot) {
            Text(stringResource(R.string.stats_snapshot_updated, stats.month, com.ticketbox.ui.components.displayDateTime(state.statsFetchedAt)),
                modifier = Modifier.testTag("stats-cached-snapshot"), style = MaterialTheme.typography.bodySmall)
        }
        if (lifestyle != null && state.lifestyleFromCache) {
            Text(stringResource(R.string.stats_lifestyle_snapshot_updated, com.ticketbox.ui.components.displayDateTime(state.lifestyleFetchedAt)),
                style = MaterialTheme.typography.bodySmall)
        }
        ProjectionRateGaps(gaps, onRepair, "stats-rate")
    }
}

@Composable
internal fun projectionAmountText(amount: Long?, currency: com.ticketbox.domain.model.CurrencyDisplay): String =
    amount?.let { com.ticketbox.ui.components.formatDisplayAmount(it, currency) }
        ?: stringResource(R.string.reports_amount_unavailable)

internal fun lifestyleRecordCurrency(expense: com.ticketbox.domain.model.Expense): com.ticketbox.domain.model.CurrencyDisplay =
    com.ticketbox.domain.model.CurrencyDisplay.forRecord(expense.homeCurrencyCode?.takeIf { it.isNotBlank() } ?: "UNKNOWN")
