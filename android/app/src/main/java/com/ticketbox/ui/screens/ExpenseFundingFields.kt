package com.ticketbox.ui.screens

import com.ticketbox.R
import androidx.compose.ui.res.stringResource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.runtime.compositionLocalOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.text.input.KeyboardType
import com.ticketbox.data.remote.dto.FinancialAccountDto
import com.ticketbox.data.repository.FundsRepository
import com.ticketbox.data.repository.ExpenseFundingInput
import com.ticketbox.data.repository.fundingInputAdapter
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.design.AppSpacing
import kotlinx.coroutines.flow.collectLatest

internal val LocalFundsRepository = compositionLocalOf<FundsRepository?> { null }

private val fundingAdapter = fundingInputAdapter

@Composable
internal fun ExpenseFundingFields(json: String, currency: CurrencyCode, enabled: Boolean, refund: Boolean = false, change: (String) -> Unit) {
    val repository = LocalFundsRepository.current ?: return
    var choose by rememberSaveable { mutableStateOf(false) }
    var attempt by remember { mutableStateOf(0) }
    val options by rememberFundingAccounts(repository, refund, attempt)
    val accounts = options.accounts
    val parsed = remember(json) { runCatching { requireNotNull(fundingAdapter.fromJson(json)) } }
    val parts = parsed.getOrDefault(emptyList())
    val editable = enabled && parsed.isSuccess
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        Text(if (refund) stringResource(R.string.funds_refund_destination) else stringResource(R.string.funds_funding_optional))
        options.message?.let { Text(it) }
        if (parsed.isFailure) Text(stringResource(R.string.funds_funding_input_unreadable))
        parts.forEachIndexed { index, row ->
            FundingPartFields(row, editable, refund, put = { next ->
                change(fundingAdapter.toJson(parts.toMutableList().also { it[index] = next }))
            }, remove = { change(fundingAdapter.toJson(parts.filterIndexed { n, _ -> n != index })) })
        }
        AppSecondaryButton(if (refund) stringResource(R.string.funds_choose_refund_account) else stringResource(R.string.funds_choose_payment_account), enabled = editable && parts.size < 8) { choose = true }
        Text(if (refund) stringResource(R.string.funds_refund_destination_note) else stringResource(R.string.funds_funding_missing_note))
    }
    if (choose) AlertDialog(onDismissRequest = { choose = false }, title = { Text(stringResource(R.string.funds_actual_funding)) }, text = {
        LazyColumn {
            items(accounts, key = { it.publicId }) { row -> TextButton(onClick = {
                change(fundingAdapter.toJson(parts + ExpenseFundingInput(java.util.UUID.randomUUID().toString(), row.publicId,
                    row.rowVersion, row.name, row.currencyCode, currency.storageKey))); choose = false
            }) { Text("${row.name} · ${row.currencyCode}") } }
            if (accounts.isEmpty()) item { Text(stringResource(R.string.funds_no_accounts)) }
        }
    }, confirmButton = { TextButton(onClick = { attempt += 1 }) { Text(stringResource(R.string.funds_refresh_accounts)) } },
        dismissButton = { TextButton(onClick = { choose = false }) { Text(stringResource(R.string.funds_back)) } })
}

@Composable
private fun FundingPartFields(row: ExpenseFundingInput, editable: Boolean, refund: Boolean,
    put: (ExpenseFundingInput) -> Unit, remove: () -> Unit) {

            Text("${row.accountName} · ${row.accountCurrency}")
            OutlinedTextField(row.expenseAmount, { value -> put(row.copy(expenseAmount = value,
                accountAmount = if (row.accountCurrency == row.expenseCurrency) value else row.accountAmount)) },
                label = { Text("${if (refund) stringResource(R.string.funds_refund_part) else stringResource(R.string.funds_expense_part)}（${row.expenseCurrency}）") }, enabled = editable, modifier = Modifier.fillMaxWidth(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), singleLine = true)
            if (row.accountCurrency != row.expenseCurrency) OutlinedTextField(row.accountAmount, { put(row.copy(accountAmount = it)) },
                label = { Text("${if (refund) stringResource(R.string.funds_refund_received) else stringResource(R.string.funds_actual_debit)}（${row.accountCurrency}）") }, enabled = editable, modifier = Modifier.fillMaxWidth(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), singleLine = true)
            TextButton(onClick = { remove() }, enabled = editable) { Text(stringResource(R.string.funds_remove_part)) }
            if (!refund) androidx.compose.foundation.layout.Row {
                androidx.compose.material3.Switch(row.includedInOpening, { put(row.copy(includedInOpening = it)) }, enabled = editable)
                Text(stringResource(R.string.funds_included_opening))
            }

}

private data class FundingAccountOptions(val accounts: List<FinancialAccountDto> = emptyList(), val message: String? = null)

@Composable
private fun rememberFundingAccounts(repository: FundsRepository, refund: Boolean, attempt: Int): androidx.compose.runtime.State<FundingAccountOptions> {
    val cachedMessage = stringResource(R.string.funds_cached_accounts_note)
    return produceState(FundingAccountOptions(), repository, refund, attempt) {
        repository.access().collectLatest { access ->
            value = FundingAccountOptions()
            if (access != null) repository.reads.accounts(access.binding).fold(
                onSuccess = { read -> value = FundingAccountOptions(
                    read.value.filterNot { it.archived || !refund && it.creditKind == "one_off" },
                    if (read.fromCache) cachedMessage else null) },
                onFailure = { value = FundingAccountOptions(message = it.message) })
        }
    }
}

@Composable
internal fun ExpenseFundingReview(state: com.ticketbox.viewmodel.ExpenseEditUiState, currency: CurrencyCode,
    canMutateFact: Boolean, commandOpen: Boolean, actions: ExpenseEditRelatedActions) {
    ExpenseFundingFields(state.fundingJson, currency, canMutateFact && state.fundingReady && !state.saving,
        change = actions.onFundingChange)
    state.fundingMessage?.let { Text(it.asString()) }
    if (state.fundingWriting) Text(stringResource(R.string.funds_funding_saving))
    if (state.fundingReviewAvailable || state.fundingReady && !commandOpen && state.fundingJson != "[]") {
        androidx.compose.material3.TextButton(onClick = actions.onFundingReview,
            enabled = !state.readOnly && !state.saving && !state.fundingWriting) { Text(stringResource(R.string.funds_funding_review_latest)) }
    }
}
