package com.ticketbox.ui.screens.plan

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppContentCard
import com.ticketbox.viewmodel.BudgetAdviceUiState
import com.ticketbox.domain.model.ReferenceRates

@Composable
internal fun AutomaticRateContent(state: BudgetAdviceUiState, actions: BudgetAdviceActions) {
    val editor = state.rateEditor
    val reference = if (editor != null) editor.reference else state.referenceRates
    AppContentCard {
        Text(stringResource(R.string.advice_reference_title), style = MaterialTheme.typography.titleMedium)
        reference?.let { ReferenceQuotes(it, editor?.rateDate) }
        state.referenceError?.let { Text(it.asString(), color = MaterialTheme.colorScheme.error) }
        TextButton(onClick = actions.onFetchRates, enabled = state.canRequest && !state.rateBusy) {
            Text(stringResource(when {
                state.rateBusy -> R.string.advice_reference_loading
                editor != null -> R.string.advice_reference_fetch_date
                else -> R.string.advice_reference_fetch
            }))
        }
        Text(stringResource(R.string.advice_reference_effect), style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
private fun ReferenceQuotes(reference: ReferenceRates, requestedDate: String?) {
    Text(stringResource(if (reference.autoEnabled) R.string.advice_reference_enabled else R.string.advice_reference_disabled))
    Text(stringResource(if (reference.provider == "frankfurter_v2") R.string.advice_reference_source_wide else R.string.advice_reference_source,
        if (reference.provider == "ecb") "ECB" else "Frankfurter"))
    val effective = reference.effective
    if (effective != null) {
        Text(stringResource(R.string.advice_reference_ready))
        Text(stringResource(R.string.advice_reference_value, effective.currencyCode, effective.rateToHome,
            effective.homeCurrencyCode, effective.rateDate))
        if (effective.source == "manual") Text(stringResource(R.string.advice_reference_override))
    } else if (requestedDate != null) Text(stringResource(R.string.advice_reference_missing_date, requestedDate))
    else if (reference.items.isEmpty()) Text(stringResource(R.string.advice_reference_empty))
    if (effective == null && reference.items.isNotEmpty()) ReferenceQuoteList(reference)
    if (reference.syncState == "error") Text(stringResource(R.string.advice_reference_retry))
}

@Composable
private fun ReferenceQuoteList(reference: ReferenceRates) {
    var expanded by rememberSaveable(reference.requestedDate, reference.items.firstOrNull()?.homeCurrencyCode) { mutableStateOf(false) }
    TextButton(onClick = { expanded = !expanded }) {
        Text(stringResource(if (expanded) R.string.plan_history_collapse else R.string.advice_reference_show_quotes,
            reference.items.size))
    }
    if (expanded) reference.items.forEach { row ->
        Text(stringResource(R.string.advice_reference_value, row.currencyCode, row.rateToHome,
            row.homeCurrencyCode, row.rateDate))
    }
}
