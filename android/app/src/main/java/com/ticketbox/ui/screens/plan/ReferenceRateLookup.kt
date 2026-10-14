package com.ticketbox.ui.screens.plan

import android.app.DatePickerDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.data.remote.dto.MissingExchangeRateDto
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.ui.components.AppContentCard
import com.ticketbox.ui.components.CurrencyChoiceField
import com.ticketbox.viewmodel.BudgetAdviceUiState
import java.time.LocalDate
import java.time.YearMonth

@Composable
internal fun ReferenceRateLookup(state: BudgetAdviceUiState, actions: BudgetAdviceActions) {
    val home = state.reportingHomeCurrencyCode ?: state.inputs?.homeCurrencyCode ?: return
    var source by rememberSaveable(state.binding, home) { mutableStateOf(if (home == "USD") "CNY" else "USD") }
    var day by rememberSaveable(state.binding, state.month) {
        mutableStateOf(minOf(YearMonth.parse(state.month).atEndOfMonth(), LocalDate.now()).toString())
    }
    val context = LocalContext.current
    AppContentCard {
        Text(stringResource(R.string.advice_reference_lookup))
        CurrencyChoiceField(CurrencyCode.fromStorageKeyOrNull(source), !state.rateBusy) { source = it.storageKey }
        TextButton(enabled = !state.rateBusy, onClick = {
            val selected = LocalDate.parse(day)
            DatePickerDialog(context, { _, year, month, date -> day = LocalDate.of(year, month + 1, date).toString() },
                selected.year, selected.monthValue - 1, selected.dayOfMonth).apply {
                datePicker.maxDate = System.currentTimeMillis()
            }.show()
        }) { Text(stringResource(R.string.advice_reference_lookup_date, day)) }
        TextButton(enabled = !state.rateBusy && source != home,
            onClick = { actions.onOpenRate(MissingExchangeRateDto(source, home, day)) }) {
            Text(stringResource(R.string.advice_reference_lookup_pair, source, home))
        }
    }
}
