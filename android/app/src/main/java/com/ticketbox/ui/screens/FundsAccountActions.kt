package com.ticketbox.ui.screens

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import com.ticketbox.R
import com.ticketbox.data.remote.dto.FinancialAccountDto
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.viewmodel.FundsUiState
import com.ticketbox.viewmodel.FundsViewModel
import com.ticketbox.viewmodel.start

@Composable
internal fun AccountActions(state: FundsUiState, detail: FinancialAccountDto, viewModel: FundsViewModel) {
    if (detail.archived || state.access?.canModify != true) return
    if (detail.kind == "credit") {
        AppPrimaryButton(stringResource(R.string.funds_record_actual_repayment), modifier = Modifier.fillMaxWidth()) { viewModel.start("repay") }
        val choices = detail.creditApplications
        if (!choices?.credits.isNullOrEmpty() && !choices.obligations.isNullOrEmpty())
            AppSecondaryButton(stringResource(R.string.funds_apply_credit), modifier = Modifier.fillMaxWidth()) { viewModel.start("apply_credit") }
    } else {
        // Recording income is the everyday action on a cash or bank account; moving money between accounts comes second.
        AppPrimaryButton(stringResource(R.string.funds_record_income), modifier = Modifier.fillMaxWidth()) { viewModel.start("income") }
        AppSecondaryButton(stringResource(R.string.funds_record_transfer), modifier = Modifier.fillMaxWidth()) { viewModel.start("transfer") }
    }
}

@Composable
internal fun AccountMore(state: FundsUiState, detail: FinancialAccountDto, viewModel: FundsViewModel) {
    var expanded by rememberSaveable(detail.publicId) { mutableStateOf(false) }
    val expansionLabel = stringResource(if (expanded) R.string.settings_account_toggle_collapse else R.string.settings_account_toggle_expand)
    TextButton(onClick = { expanded = !expanded }, modifier = Modifier.semantics { stateDescription = expansionLabel }) {
        Text(stringResource(R.string.funds_account_more))
    }
    if (!expanded) return
    Text(stringResource(R.string.funds_opening_line, detail.openingDate, detail.openingSource), style = MaterialTheme.typography.bodySmall)
    detail.creditTerms?.let { FundsCreditTermsRead(it, detail.currencyCode) }
    if (state.access?.canModify != true) return
    if (detail.canEdit) AppSecondaryButton(stringResource(R.string.funds_edit_account)) { viewModel.start("edit") }
    if (detail.archived) return
    if (detail.canEdit) AppSecondaryButton(stringResource(R.string.funds_reconcile)) { viewModel.start("reconciliation") }
    if (detail.kind == "credit") {
        AppSecondaryButton(stringResource(R.string.funds_incur_fee)) { viewModel.start("incur_fee") }
        if (state.installments?.agreements.isNullOrEmpty())
            AppSecondaryButton(stringResource(R.string.funds_add_agreement)) { viewModel.start("installments") }
    } else {
        AppSecondaryButton(stringResource(R.string.funds_record_loan)) { viewModel.start("loan") }
    }
}
