package com.ticketbox.ui.screens.recurring

import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.data.remote.dto.RecurringOccurrenceDto
import com.ticketbox.ui.components.displayDateTime

@Composable
internal fun OccurrenceDefinitionBasis(occurrence: RecurringOccurrenceDto) {
    Text(stringResource(R.string.recurring_definition_current), style = MaterialTheme.typography.titleMedium)
    Text(stringResource(R.string.recurring_history_monthly_amount,
        recurringRecordedAmountText(occurrence.plannedAmountCents, occurrence.homeCurrencyCode)))
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
