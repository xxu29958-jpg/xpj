package com.ticketbox.ui.screens.recurring

import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.data.repository.PendingOccurrencePayment

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
        occurrencePaymentAmountText(intent.paymentAmountCents, intent.paymentCurrencyCode)))
}

@Composable
internal fun occurrencePaymentAmountText(amount: Long?, currencyCode: String?): String =
    amount?.let { recurringRecordedAmountText(it, currencyCode) }
        ?: stringResource(R.string.occurrence_payment_amount_unknown)
