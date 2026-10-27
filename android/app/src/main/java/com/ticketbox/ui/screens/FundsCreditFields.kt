package com.ticketbox.ui.screens

import com.ticketbox.R
import androidx.compose.ui.res.stringResource
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import com.ticketbox.domain.model.AccountChoice
import com.ticketbox.domain.model.CreditTerms
import com.ticketbox.data.repository.FundsInput
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.presentation.formatDisplayAmount
import com.ticketbox.viewmodel.FundsViewModel


@Composable
internal fun FundsAccountChoices(choices: List<AccountChoice>, enabled: Boolean, vm: FundsViewModel) {
    var choosing by rememberSaveable { mutableStateOf(false) }
    if (choices.isNotEmpty()) AppSecondaryButton(stringResource(R.string.funds_choose_preset), enabled = enabled) { choosing = true }
    if (choosing) AlertDialog(onDismissRequest = { choosing = false }, title = { Text(stringResource(R.string.funds_preset_title)) },
        text = { LazyColumn { items(choices, key = { it.key }) { choice ->
            TextButton(enabled = enabled, onClick = {
                vm.edit { it.copy(name = choice.name, kind = choice.kind, institution = choice.institution) }
                choosing = false
            }) { Text(choice.name) }
        } } }, confirmButton = { TextButton(onClick = { choosing = false }) { Text(stringResource(R.string.funds_back)) } })
    Text(stringResource(R.string.funds_preset_note), style = MaterialTheme.typography.bodySmall)
}

@Composable
internal fun FundsCreditTermsFields(input: FundsInput, enabled: Boolean, vm: FundsViewModel) {
    Text(stringResource(R.string.funds_terms_title), style = MaterialTheme.typography.titleMedium)
    Text(stringResource(R.string.funds_credit_not_asset), style = MaterialTheme.typography.bodySmall)
    FundsField(stringResource(R.string.funds_credit_limit, input.currency), input.creditLimit, enabled, money = true) { value -> vm.edit { it.copy(creditLimit = value) } }
    FundsField(stringResource(R.string.funds_available_credit), input.availableCredit, enabled, money = true) { value -> vm.edit { it.copy(availableCredit = value) } }
    FundsField(stringResource(R.string.funds_credit_observed_on), input.creditObservedOn, enabled) { value -> vm.edit { it.copy(creditObservedOn = value) } }
    FundsField(stringResource(R.string.funds_credit_source), input.creditSource, enabled) { value -> vm.edit { it.copy(creditSource = value) } }
    FundsField(stringResource(R.string.funds_statement_day), input.statementDay, enabled) { value -> vm.edit { it.copy(statementDay = value) } }
    FundsField(stringResource(R.string.funds_due_day), input.paymentDueDay, enabled) { value -> vm.edit { it.copy(paymentDueDay = value) } }
    Text(stringResource(R.string.funds_terms_note), style = MaterialTheme.typography.bodySmall)
}

@Composable
internal fun FundsCreditTermsRead(terms: CreditTerms, currency: String) {
    val unrecorded = stringResource(R.string.funds_unrecorded)
    fun amount(value: Long?) = value?.let { formatDisplayAmount(it, CurrencyDisplay.forRecord(currency)) } ?: unrecorded
    Text(stringResource(R.string.funds_credit_summary, amount(terms.creditLimitMinor), amount(terms.availableCreditMinor)))
    terms.observedOn?.let { Text(stringResource(R.string.funds_credit_observation, it, terms.source.orEmpty()), style = MaterialTheme.typography.bodySmall) }
    if (terms.statementDay != null || terms.paymentDueDay != null)
        Text(stringResource(R.string.funds_billing_days, terms.statementDay?.toString() ?: stringResource(R.string.funds_unrecorded), terms.paymentDueDay?.toString() ?: stringResource(R.string.funds_unrecorded)), style = MaterialTheme.typography.bodySmall)
}
