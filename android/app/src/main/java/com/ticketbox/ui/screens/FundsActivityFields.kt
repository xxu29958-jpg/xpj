package com.ticketbox.ui.screens

import com.ticketbox.R
import androidx.compose.ui.res.stringResource
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import com.ticketbox.domain.model.FinancialAccount
import com.ticketbox.data.repository.FundsInput
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.CurrencyChoiceField
import com.ticketbox.viewmodel.FundsViewModel
import com.ticketbox.viewmodel.choosePayer

@Composable
internal fun FundsActivityFields(input: FundsInput, accounts: List<FinancialAccount>, enabled: Boolean, vm: FundsViewModel) {
    Text(when (input.mode) {
        "income" -> stringResource(R.string.funds_income_note)
        "loan" -> stringResource(R.string.funds_loan_note)
        "transfer" -> stringResource(R.string.funds_transfer_note)
        else -> stringResource(R.string.funds_observation_note)
    })
    val label = when (input.mode) {
        "reconciliation" -> if (input.kind == "credit") stringResource(R.string.funds_observed_debt) else stringResource(R.string.funds_observed_balance)
        "transfer" -> stringResource(R.string.funds_transfer_sent)
        else -> stringResource(R.string.funds_income_received)
    }
    FundsField("$label（${input.currency}）", input.activityAmount, enabled, money = true) { value -> vm.edit { it.copy(activityAmount = value) } }
    when (input.mode) {
        "transfer" -> FundsTransferFields(input, accounts, enabled, vm)
        "loan" -> {
            FundsField(stringResource(R.string.funds_loan_name), input.loanName, enabled) { value -> vm.edit { it.copy(loanName = value) } }
            CurrencyChoiceField(CurrencyCode.fromStorageKeyOrNull(input.loanCurrency), enabled, title = stringResource(R.string.funds_loan_currency)) { currency -> vm.edit { it.copy(loanCurrency = currency.storageKey) } }
            FundsField(stringResource(R.string.funds_loan_principal, input.loanCurrency), input.loanPrincipal, enabled, money = true) { value -> vm.edit { it.copy(loanPrincipal = value) } }
            Text(stringResource(R.string.funds_loan_amount_note))
        }
        "reconciliation" -> {
            Row {
                Switch(input.applyAdjustment, { value -> vm.edit { it.copy(applyAdjustment = value) } }, enabled = enabled)
                Text(stringResource(R.string.funds_apply_adjustment))
            }
            Text(stringResource(R.string.funds_observation_only_note))
        }
    }
    FundsField(stringResource(R.string.funds_source_note), input.note, enabled) { value -> vm.edit { it.copy(note = value) } }
}

@Composable
private fun FundsTransferFields(input: FundsInput, accounts: List<FinancialAccount>, enabled: Boolean, vm: FundsViewModel) {
    var choosing by rememberSaveable { mutableStateOf(false) }
    AppSecondaryButton(input.payerName.ifBlank { stringResource(R.string.funds_choose_receiver) }, enabled = enabled) { choosing = true }
    if (choosing) AlertDialog(onDismissRequest = { choosing = false }, title = { Text(stringResource(R.string.funds_receiver_account)) },
        text = { LazyColumn { items(accounts.filter { it.kind != "credit" && !it.archived && it.publicId != input.accountId }) { account ->
            TextButton(onClick = { vm.choosePayer(account); choosing = false }) { Text("${account.name} · ${account.currencyCode}") }
        } } }, confirmButton = { TextButton(onClick = { choosing = false }) { Text(stringResource(R.string.funds_back)) } })
    FundsField(stringResource(R.string.funds_receiver_amount, input.payerCurrency.ifBlank { stringResource(R.string.funds_choose_account_first) }), input.otherAmount, enabled, money = true) { value -> vm.edit { it.copy(otherAmount = value) } }
}
