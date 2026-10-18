package com.ticketbox.ui.screens

import com.ticketbox.R
import androidx.compose.ui.res.stringResource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.key
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.snapshotFlow
import androidx.compose.foundation.text.input.rememberTextFieldState
import androidx.compose.foundation.text.input.setTextAndPlaceCursorAtEnd
import androidx.compose.runtime.setValue
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.text.input.KeyboardType
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.remote.dto.FinancialAccountDto
import com.ticketbox.data.repository.FundsInput
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.CurrencyChoiceField
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.FundsUiState
import com.ticketbox.viewmodel.FundsViewModel
import com.ticketbox.viewmodel.choosePayer

@Composable
internal fun FundsEditor(state: FundsUiState, input: FundsInput, vm: FundsViewModel) {
    val enabled = !state.task.frozen && !state.busy && state.access?.canModify == true && state.access.binding == input.binding
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        if (input.binding != state.access?.binding) Text(stringResource(R.string.funds_original_binding_note))
        key(input.key) {
            FundsInputFields(state, input, enabled, vm)
            if (input.mode !in setOf("edit", "funding", "envelopes", "apply_credit", "void_credit")) FundsField("${if (input.mode == "create") stringResource(R.string.funds_opening_date) else stringResource(R.string.funds_actual_date)}（YYYY-MM-DD）", input.date, enabled) { value -> vm.edit { it.copy(date = value) } }
        }
        FundsSubmission(state, enabled, vm)
    }
}

@Composable
private fun FundsInputFields(state: FundsUiState, input: FundsInput, enabled: Boolean, vm: FundsViewModel) {
    when (input.mode) {
            "apply_credit", "void_credit" -> CreditApplicationFields(state, input, enabled, vm)
            "incur_fee" -> CreditFeeFields(state, input, enabled, vm)
            "envelopes" -> EnvelopeFields(state, input, enabled, vm)
            "void_repayment" -> {
                FundsVoidPaymentFields(input, enabled, vm)
            }
            "funding" -> {
                CurrencyCode.fromStorageKeyOrNull(input.currency)?.let { currency ->
                    ExpenseFundingFields(input.fundingJson, currency, enabled) { value -> vm.edit { it.copy(fundingJson = value) } }
                }
                FundsField(stringResource(R.string.funds_review_reason), input.note, enabled) { value -> vm.edit { it.copy(note = value) } }
            }
            "repay" -> {
                FundsCaptureFields(input, enabled, vm)
                FundsPaymentFields(input, state.accounts, enabled, vm)
                CreditFeePaymentFields(state, input, enabled, vm)
                InstallmentPaymentFields(input, state.installments, enabled, vm)
            }
            "installments" -> InstallmentFields(input, state.installments, enabled, vm)
            "create", "edit" -> AccountEditorFields(state, input, enabled, vm)
            else -> FundsActivityFields(input, state.accounts, enabled, vm)
            }
}

@Composable
private fun AccountEditorFields(state: FundsUiState, input: FundsInput, enabled: Boolean, vm: FundsViewModel) {

                if (input.mode == "create") FundsAccountChoices(state.accountChoices, enabled, vm)
                FundsAccountFields(input, enabled, vm)
                if (input.mode == "create") ExistingDebtField(input, state.existingDebts, enabled, vm)
                if (input.kind == "credit") FundsCreditTermsFields(input, enabled, vm)

}

@Composable
private fun ExistingDebtField(input: FundsInput, choices: List<com.ticketbox.data.remote.dto.ExistingDebtChoiceDto>, enabled: Boolean, vm: FundsViewModel) {
    var expanded by rememberSaveable { mutableStateOf(false) }
    TextButton(onClick = { expanded = true }, enabled = enabled) {
        Text(if (input.existingDebtId.isBlank()) stringResource(R.string.funds_adopt_debt) else stringResource(R.string.funds_adopt_selected, input.existingDebtLabel))
    }
    DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
        DropdownMenuItem(text = { Text(stringResource(R.string.funds_no_old_debt)) }, onClick = {
            vm.edit { it.copy(existingDebtId = "", existingDebtVersion = 0, existingDebtLabel = "") }; expanded = false
        }, enabled = enabled)
        choices.forEach { debt ->
            val label = stringResource(R.string.funds_old_debt_label, debt.name, money(debt.remainingHomeMinor, debt.homeCurrencyCode))
            DropdownMenuItem(text = {
            Text(stringResource(R.string.funds_old_debt_choice, debt.name, money(debt.remainingHomeMinor, debt.homeCurrencyCode), debt.earliestOpeningDate))
        }, onClick = {
            vm.edit { it.copy(kind = "credit", existingDebtId = debt.publicId, existingDebtVersion = debt.rowVersion,
                existingDebtLabel = label) }; expanded = false
        }, enabled = enabled) }
    }
    if (input.existingDebtId.isNotBlank()) Text(stringResource(R.string.funds_adopt_note), style = MaterialTheme.typography.bodySmall)
}

@Composable
private fun FundsAccountFields(input: FundsInput, enabled: Boolean, vm: FundsViewModel) {
    FundsField(stringResource(R.string.funds_account_name), input.name, enabled) { value -> vm.edit { it.copy(name = value) } }
    if (input.mode == "create") {
        androidx.compose.foundation.layout.FlowRow(horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            fundKinds().forEach { (kind, label) -> FilterChip(input.kind == kind, { vm.edit { it.copy(kind = kind) } }, { Text(label) }, enabled = enabled) }
        }
        CurrencyChoiceField(CurrencyCode.fromStorageKeyOrNull(input.currency), enabled, title = stringResource(R.string.funds_choose_currency)) { value -> vm.edit { it.copy(currency = value.storageKey) } }
        FundsField(if (input.kind == "credit") stringResource(R.string.funds_opening_debt, input.currency) else stringResource(R.string.funds_opening_balance, input.currency), input.opening, enabled, money = true) { value -> vm.edit { it.copy(opening = value) } }
        Text(stringResource(R.string.funds_opening_unknown_note), style = MaterialTheme.typography.bodySmall)
        FundsField(stringResource(R.string.funds_opening_source), input.source, enabled) { value -> vm.edit { it.copy(source = value) } }
    } else Row {
        Switch(input.archived, { value -> vm.edit { it.copy(archived = value) } }, enabled = enabled)
        Text(stringResource(R.string.funds_archive_note))
    }
    FundsField(stringResource(R.string.funds_institution), input.institution, enabled) { value -> vm.edit { it.copy(institution = value) } }
    Row { Switch((input.visibilityEdit ?: input.visibility) == "ledger", { shared -> vm.edit {
        val value = if (shared) "ledger" else "private"
        if (it.mode == "edit") it.copy(visibilityEdit = value) else it.copy(visibility = value)
    } }, enabled = enabled)
        Text(stringResource(R.string.funds_share_with_ledger)) }
    Text(stringResource(R.string.funds_privacy_note), style = MaterialTheme.typography.bodySmall)
    FundsField(stringResource(R.string.funds_tail), input.tail, enabled) { value -> vm.edit { it.copy(tail = value) } }
}

@Composable
private fun FundsPaymentFields(input: FundsInput, accounts: List<FinancialAccountDto>, enabled: Boolean, vm: FundsViewModel) {
    var choosing by rememberSaveable { mutableStateOf(false) }
    Text(stringResource(R.string.funds_payment_note, input.name))
    AppSecondaryButton(input.payerName.ifBlank { stringResource(R.string.funds_choose_payer) }, enabled = enabled) { choosing = true }
    if (choosing) AlertDialog(onDismissRequest = { choosing = false }, title = { Text(stringResource(R.string.funds_payer_account)) },
        text = { androidx.compose.foundation.lazy.LazyColumn {
            items(accounts.filter { it.kind != "credit" && !it.archived }, key = { it.publicId }) { account ->
                TextButton(onClick = { vm.choosePayer(account); choosing = false }) { Text("${account.name} · ${account.currencyCode}") }
            }
        } }, confirmButton = { TextButton(onClick = { choosing = false }) { Text(stringResource(R.string.funds_back)) } })
    FundsField(stringResource(R.string.funds_principal, input.currency), input.principal, enabled, money = true) { value -> vm.edit {
        it.copy(principal = value, paid = if (it.currency == it.payerCurrency) value else it.paid)
    } }
    FundsField(stringResource(R.string.funds_payer_principal, input.payerCurrency.ifBlank { stringResource(R.string.funds_payer_currency_first) }), input.paid, enabled, money = true) { value -> vm.edit { it.copy(paid = value) } }
    FundsField(stringResource(R.string.funds_new_fee, input.payerCurrency.ifBlank { stringResource(R.string.funds_payer_currency_first) }), input.newFee, enabled, money = true) { value -> vm.edit { it.copy(newFee = value) } }
    FundsField(stringResource(R.string.funds_fee_source), input.feeNote, enabled) { value -> vm.edit { it.copy(feeNote = value) } }
    Text(stringResource(R.string.funds_fee_note), style = MaterialTheme.typography.bodySmall)
    FundsField(stringResource(R.string.funds_note), input.note, enabled) { value -> vm.edit { it.copy(note = value) } }
}

@Composable
private fun FundsSubmission(state: FundsUiState, editable: Boolean, vm: FundsViewModel) {
    val original = state.task.original
    when {
        original?.status == PendingMutationStatus.Done -> {
            Text(stringResource(R.string.funds_saved))
            AppPrimaryButton(stringResource(R.string.funds_finish_view), enabled = !state.busy, onClick = vm::finish)
        }
        state.task.frozen -> {
            Text(original?.lastError ?: stringResource(R.string.funds_receipt_pending))
            if (original == null) AppPrimaryButton(stringResource(R.string.funds_continue_original), enabled = !state.busy, onClick = vm::submit)
            if (original?.status == PendingMutationStatus.Failed) AppSecondaryButton(stringResource(R.string.funds_retry_original), enabled = !state.busy, onClick = vm::retry)
            if (original?.status == PendingMutationStatus.Conflict || original?.lastError?.startsWith(com.ticketbox.data.repository.FUNDS_REFUSED) == true)
                AppSecondaryButton(stringResource(R.string.funds_review_continue), enabled = !state.busy, onClick = vm::review)
        }
        else -> {
            AppPrimaryButton(stringResource(R.string.funds_confirm_save), enabled = editable, onClick = vm::submit)
            AppSecondaryButton(stringResource(R.string.funds_abandon_input), enabled = !state.busy, onClick = vm::finish)
        }
    }
}

@Composable
internal fun FundsField(label: String, value: String, enabled: Boolean, money: Boolean = false, change: (String) -> Unit) {
    val editor = rememberTextFieldState(value)
    val onChange by rememberUpdatedState(change)
    var published by remember { mutableStateOf(value) }
    LaunchedEffect(editor) {
        snapshotFlow { editor.text.toString() }.collect { latest ->
            if (latest != published) { published = latest; onChange(latest) }
        }
    }
    SideEffect {
        if (value != published) { published = value; editor.setTextAndPlaceCursorAtEnd(value) }
    }
    AppTextInput(AppTextInputState(label, value, enabled = enabled, editorState = editor,
        keyboardOptions = KeyboardOptions(keyboardType = if (money) KeyboardType.Decimal else KeyboardType.Text)),
        AppTextInputActions(onValueChange = change))
}
