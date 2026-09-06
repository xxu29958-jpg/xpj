package com.ticketbox.ui.screens.recurring

import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.data.repository.PendingOccurrencePayment
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.components.formatDisplayAmount

/** Frozen intent context remains readable even when the server and period list are unavailable. */
@Composable
internal fun RecurringOccurrenceIntentSummary(pending: PendingOccurrencePayment) {
    val intent = pending.intent
    if (intent == null) {
        Text(stringResource(R.string.occurrence_unsupported))
        return
    }
    Text(intent.seriesLabel + " · " + intent.period)
    if (intent.request.action == "clear") Text(stringResource(R.string.occurrence_clear_review))
    else Text(stringResource(R.string.occurrence_link_review, intent.paymentLabel.orEmpty(),
        formatDisplayAmount(intent.paymentAmountCents ?: 0, CurrencyDisplay.forRecord(intent.homeCurrencyCode))))
}
