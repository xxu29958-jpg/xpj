package com.ticketbox.ui.screens.recurring

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.data.repository.RecurringPendingIntent
import com.ticketbox.data.repository.RecurringPendingKind
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing

/** Per-currency display only. Cross-currency conversion remains the backend projection owner's job. */
@Composable
internal fun recurringTotalLines(model: RecurringHeroModel): List<String> {
    if (model.amountsByCurrency.isEmpty()) return listOf(stringResource(R.string.recurring_total_empty))
    val unavailable = stringResource(R.string.recurring_total_unavailable)
    return model.amountsByCurrency.map { (code, amount) ->
        if (amount == null) unavailable
        else "$code ${formatDisplayAmount(amount, CurrencyDisplay.forRecord(code))}"
    }
}

@Composable
internal fun recurringRecordedAmountText(amount: Long, homeCurrencyCode: String?): String {
    val currency = CurrencyCode.fromStorageKeyOrNull(homeCurrencyCode)
    return when {
        currency != null -> "${currency.storageKey} ${formatDisplayAmount(amount, CurrencyDisplay(currency))}"
        homeCurrencyCode.isNullOrBlank() -> stringResource(R.string.recurring_original_amount_unknown, amount)
        else -> formatDisplayAmount(amount, CurrencyDisplay.forRecord(homeCurrencyCode))
    }
}

@Composable
internal fun RecurringManualIntentSummary(original: RecurringPendingIntent) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
        Text(stringResource(if (original.kind == RecurringPendingKind.CREATE) R.string.recurring_form_title_create else R.string.recurring_form_title_edit))
        Text(original.merchant ?: stringResource(R.string.recurring_pending_update_unknown))
        original.baselineAmountCents?.let { Text(recurringRecordedAmountText(it, original.homeCurrencyCode)) }
        if (original.nextExpectedDateChanged) {
            Text(original.nextExpectedDate?.let(::recurringDisplayDate) ?: stringResource(R.string.recurring_form_date_none))
        }
        if (!original.hasSupportedIntent) Text(stringResource(R.string.recurring_original_unsupported))
    }
}
