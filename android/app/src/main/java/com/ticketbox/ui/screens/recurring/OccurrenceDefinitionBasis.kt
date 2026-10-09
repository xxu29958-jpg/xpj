package com.ticketbox.ui.screens.recurring

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.data.remote.dto.RecurringOccurrenceDto
import com.ticketbox.ui.components.displayDateTime
import com.ticketbox.ui.components.AppAmountText
import com.ticketbox.ui.components.AppPaperCard
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStateTokens

@Composable
internal fun OccurrenceCurrentSummary(occurrence: RecurringOccurrenceDto) {
    val tones = LocalStateTokens.current
    val palette = when (occurrence.state) {
        "fulfilled" -> tones.success
        "needs_review", "unfulfilled" -> tones.warn
        else -> tones.neutral
    }
    AppPaperCard(containerColor = palette.bg) {
        Column(Modifier.fillMaxWidth().padding(AppSpacing.cardPadding),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            Text(stringResource(occurrenceStateLabel(occurrence.state)), Modifier.testTag("occurrence-state"),
                color = palette.fg, style = MaterialTheme.typography.titleMedium)
            Text(stringResource(R.string.occurrence_summary_period, occurrence.period), style = MaterialTheme.typography.bodySmall)
            Text(stringResource(R.string.occurrence_planned_amount), style = MaterialTheme.typography.bodyMedium)
            AppAmountText(recurringRecordedAmountText(occurrence.plannedAmountCents, occurrence.homeCurrencyCode), role = AppAmountRole.Hero)
            Text(stringResource(R.string.occurrence_reserved,
                recurringRecordedAmountText(occurrence.reservedAmountCents, occurrence.homeCurrencyCode)))
            occurrence.paidAmountCents?.let {
                Text(stringResource(R.string.occurrence_paid_amount, recurringRecordedAmountText(it, occurrence.paidHomeCurrencyCode)))
            }
        }
    }
}

@Composable
internal fun OccurrenceDefinitionBasis(occurrence: RecurringOccurrenceDto) {
    HorizontalDivider()
    val original = occurrence.recordedDefinition
    if (original == null) {
        Text(stringResource(if (occurrence.rowVersion == 0L) R.string.recurring_definition_unrecorded
            else R.string.recurring_definition_unknown))
    } else {
        Text(stringResource(R.string.recurring_definition_recorded, original.seriesRowVersion),
            style = MaterialTheme.typography.titleMedium)
        Text(stringResource(R.string.recurring_history_saved_at, displayDateTime(original.recordedAt)))
        RecurringDefinitionContent(original.snapshot)
    }
    HorizontalDivider()
}

private fun occurrenceStateLabel(state: String): Int = when (state) {
    "fulfilled" -> R.string.occurrence_fulfilled
    "needs_review" -> R.string.occurrence_review
    "unfulfilled" -> R.string.occurrence_unfulfilled
    else -> R.string.occurrence_unknown
}
