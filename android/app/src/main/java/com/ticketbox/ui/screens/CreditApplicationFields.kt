package com.ticketbox.ui.screens

import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
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
import com.ticketbox.domain.model.CreditApplicationChoice
import com.ticketbox.domain.model.CreditApplicationHistory
import com.ticketbox.domain.model.FinancialAccount
import com.ticketbox.data.repository.FundsInput
import com.ticketbox.viewmodel.FundsUiState
import com.ticketbox.viewmodel.FundsViewModel
import com.ticketbox.viewmodel.voidCreditApplication

@Composable
internal fun CreditApplicationFields(state: FundsUiState, input: FundsInput, enabled: Boolean, vm: FundsViewModel) {
    Text(stringResource(if (input.mode == "void_credit") R.string.funds_void_credit_note else R.string.funds_apply_credit_note))
    if (input.mode == "void_credit") state.detail?.creditApplications?.history?.firstOrNull {
        it.publicId == input.creditReviewId
    }?.let { CreditApplicationSummary(it, input.currency) }
    if (input.mode == "apply_credit") {
        CreditApplicationChoice(true, input, state.detail?.creditApplications?.credits.orEmpty(), enabled) { row, label ->
            vm.edit { it.copy(creditSourceId = row.publicId, creditSourceLabel = label) }
        }
        CreditApplicationChoice(false, input, state.detail?.creditApplications?.obligations.orEmpty(), enabled) { row, label ->
            vm.edit { it.copy(creditDrawId = row.publicId, creditDrawLabel = label) }
        }
        FundsField(stringResource(R.string.funds_credit_apply_amount, input.currency), input.activityAmount, enabled, money = true) {
            value -> vm.edit { it.copy(activityAmount = value) }
        }
    }
    FundsField(stringResource(if (input.mode == "void_credit") R.string.funds_credit_void_reason else R.string.funds_credit_review_reason),
        input.note, enabled) { value -> vm.edit { it.copy(note = value) } }
}

@Composable
private fun CreditApplicationChoice(source: Boolean, input: FundsInput, choices: List<CreditApplicationChoice>,
    enabled: Boolean, choose: (CreditApplicationChoice, String) -> Unit) {
    val title = stringResource(if (source) R.string.funds_application_source else R.string.funds_credit_target)
    val saved = if (source) input.creditSourceLabel else input.creditDrawLabel
    val id = if (source) input.creditSourceId else input.creditDrawId
    val current = choices.firstOrNull { it.publicId == id }
    val label = current?.let { stringResource(R.string.funds_credit_choice, it.note, it.occurredOn, money(it.remainingMinor, input.currency)) }
    var expanded by rememberSaveable { mutableStateOf(false) }
    Text(title, style = MaterialTheme.typography.labelLarge)
    TextButton(enabled = enabled, onClick = { expanded = true }) { Text(label ?: saved.ifBlank { title }) }
    DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
        choices.forEach { row ->
            val label = stringResource(R.string.funds_credit_choice, row.note, row.occurredOn, money(row.remainingMinor, input.currency))
            DropdownMenuItem(text = { Text(label) }, onClick = { choose(row, label); expanded = false })
        }
    }
    if (choices.isEmpty() || (id.isNotBlank() && choices.none { it.publicId == id })) Text(stringResource(R.string.funds_credit_no_choices), style = MaterialTheme.typography.bodySmall)
}

@Composable
internal fun CreditApplicationsRead(detail: FinancialAccount, canModify: Boolean, vm: FundsViewModel) {
    val data = detail.creditApplications ?: return
    val currency = detail.currencyCode
    if (data.history.isEmpty()) return
    Text(stringResource(R.string.funds_credit_history), style = MaterialTheme.typography.titleMedium)
    data.history.forEach { row ->
        CreditApplicationSummary(row, currency)
        if (row.voidReason != null) Text(stringResource(R.string.funds_credit_voided, row.voidReason))
        else {
            if (row.appliedMinor < row.amountMinor) Text(stringResource(R.string.funds_credit_changed))
            if (canModify) TextButton(onClick = { vm.voidCreditApplication(row.publicId) }) { Text(stringResource(R.string.funds_void_credit)) }
        }
    }
}

@Composable
private fun CreditApplicationSummary(row: CreditApplicationHistory, currency: String) {
    Text("${row.creditNote} → ${row.drawNote}")
    Text(stringResource(R.string.funds_credit_applied, money(row.amountMinor, currency), money(row.appliedMinor, currency)))
    Text(row.reason, style = MaterialTheme.typography.bodySmall)
}
