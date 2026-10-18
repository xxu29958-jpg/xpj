package com.ticketbox.ui.screens

import com.ticketbox.ui.asString
import com.ticketbox.R
import com.ticketbox.viewmodel.openEnvelopes
import androidx.compose.ui.res.stringResource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import com.ticketbox.data.remote.dto.FinancialAccountDto
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.components.AppListRow
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryRefreshState
import com.ticketbox.ui.components.AppSecondaryScrollableContent
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.FundsUiState
import com.ticketbox.viewmodel.FundsViewModel
import com.ticketbox.viewmodel.start
import com.ticketbox.viewmodel.voidPayment

@Composable
internal fun fundKinds() = linkedMapOf("cash" to stringResource(R.string.funds_kind_cash), "bank" to stringResource(R.string.funds_kind_bank), "wallet" to stringResource(R.string.funds_kind_wallet), "credit" to stringResource(R.string.funds_kind_credit))
@Composable
internal fun fundActions() = mapOf("create" to stringResource(R.string.funds_add_account), "edit" to stringResource(R.string.funds_edit_account), "repay" to stringResource(R.string.funds_record_repayment),
    "incur_fee" to stringResource(R.string.funds_incur_fee),
    "void_repayment" to stringResource(R.string.funds_void_payment),
    "envelopes" to stringResource(R.string.envelopes_edit),
    "income" to stringResource(R.string.funds_record_income), "loan" to stringResource(R.string.funds_record_loan), "transfer" to stringResource(R.string.funds_record_transfer), "reconciliation" to stringResource(R.string.funds_reconcile), "funding" to stringResource(R.string.funds_funding_title), "installments" to stringResource(R.string.funds_record_installments))
internal fun money(value: Long, currency: String) = formatDisplayAmount(value, CurrencyDisplay.forRecord(currency))
@Composable
private fun FinancialAccountDto.balanceLabel(): String = when {
    balanceMinor == null -> stringResource(R.string.funds_unknown_balance)
    kind == "credit" && balanceMinor <= 0 -> stringResource(R.string.funds_debt_balance, money(-balanceMinor, currencyCode))
    kind == "credit" -> stringResource(R.string.funds_overpayment_balance, money(balanceMinor, currencyCode))
    else -> money(balanceMinor, currencyCode)
}

@Composable
fun FundsScreen(viewModel: FundsViewModel, onBack: () -> Unit, onExpense: (Long) -> Unit) {
    val state by viewModel.state
    val input = state.task.input
    val detail = state.detail
    AppSecondaryScrollableContent(
        chrome = AppSecondaryPageChrome(AppPageRole.Ledger, fundsTitle(state),
            stringResource(if (state.envelopeMonth != null) R.string.envelopes_subtitle else R.string.funds_accounts_subtitle),
            stringResource(R.string.funds_back), { if (!viewModel.back()) onBack() }),
        refresh = AppSecondaryRefreshState(state.loading, viewModel::refresh),
    ) {
        state.error?.let { message -> item { Text(message.asString(), color = MaterialTheme.colorScheme.error) } }
        if (state.fromCache) item { Text(stringResource(R.string.funds_cached_note), style = MaterialTheme.typography.bodySmall) }
        when {
            state.editing && input != null -> item { FundsEditor(state, input, viewModel) }
            state.envelopeMonth != null -> item { EnvelopeOverview(state, viewModel) }
            state.fundingPage -> item { FundingReadPanel(state, viewModel) }
            state.captureRequested -> captureAccounts(state, viewModel)
            detail != null -> accountDetail(state, detail, viewModel, onExpense)
            else -> accountsOverview(state, viewModel)
        }
    }
}

@Composable
private fun fundsTitle(state: FundsUiState): String = when {
    state.editing -> fundActions()[state.task.input?.mode] ?: stringResource(R.string.funds_task_title)
    state.envelopeMonth != null -> stringResource(R.string.envelopes_title)
    state.fundingPage -> stringResource(R.string.funds_funding_title)
    else -> state.detail?.name ?: stringResource(R.string.funds_accounts_title)
}

@Composable
private fun FundingReadPanel(state: FundsUiState, viewModel: FundsViewModel) {
    val input = state.task.input

    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        Text(stringResource(R.string.funds_funding_change_note))
        state.funding?.let { source ->
            if (source.parts.isEmpty()) Text(stringResource(R.string.funds_unfunded))
            source.parts.forEach { part -> Text(stringResource(R.string.funds_funding_part, part.accountName, money(part.expenseAmountMinor, source.currencyCode)) +
                if (part.includedInOpening) stringResource(R.string.funds_opening_suffix) else "") }
            if (source.canEdit && state.access?.canModify == true) AppPrimaryButton(
                if (input != null) stringResource(R.string.funds_continue_task) else stringResource(R.string.funds_review_funding)) { viewModel.start("funding") }
        }
        if (input != null && state.funding?.canEdit != true) AppSecondaryButton(stringResource(R.string.funds_view_task), onClick = viewModel::resume)
    }

}

private fun LazyListScope.accountDetail(state: FundsUiState, detail: FinancialAccountDto, viewModel: FundsViewModel, onExpense: (Long) -> Unit) {

    item { AccountDetailHeader(state, detail, viewModel) }
    items(detail.feeObligations, key = { "fee:${it.expenseId}" }) { fee ->
        AppListRow(onClick = { onExpense(fee.expenseId) }) {
            Text(stringResource(R.string.funds_fee_owed, fee.note, fee.occurredOn, money(fee.remainingMinor, detail.currencyCode)))
        }
    }
    items(detail.movements, key = { it.publicId }) { row ->
        AppListRow(onClick = row.expenseId?.let { id -> { onExpense(id) } }) {
            Column(Modifier.weight(1f)) {
                Text(row.note); Text(row.occurredOn, style = MaterialTheme.typography.bodySmall)
                if (row.canVoidRepayment && row.repaymentPublicId != null && state.access?.canModify == true)
                    TextButton(onClick = { viewModel.voidPayment(row.repaymentPublicId) }) { Text(stringResource(R.string.funds_void_payment)) }
            }
            Text(money(row.amountMinor, detail.currencyCode))
        }
    }

}

@Composable
private fun AccountDetailHeader(state: FundsUiState, detail: FinancialAccountDto, viewModel: FundsViewModel) {

    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        Text(detail.balanceLabel(), style = MaterialTheme.typography.headlineMedium)
        Text("${fundKinds()[detail.kind]} · ${if (detail.visibility == "private") stringResource(R.string.funds_private_visibility) else stringResource(R.string.funds_ledger_visibility)}" +
            (detail.tail?.let { stringResource(R.string.funds_tail_suffix, it) } ?: ""))
        Text(stringResource(R.string.funds_opening_line, detail.openingDate, detail.openingSource), style = MaterialTheme.typography.bodySmall)
        detail.creditTerms?.let { FundsCreditTermsRead(it, detail.currencyCode) }
        if (detail.unallocatedCreditMinor > 0) Text(stringResource(R.string.funds_unallocated_credit_note, money(detail.unallocatedCreditMinor, detail.currencyCode)))
        if (detail.balanceMinor == null) Text(stringResource(R.string.funds_recorded_change_note, money(detail.recordedChangeMinor, detail.currencyCode)))
        detail.observation?.let { check -> Text(stringResource(R.string.funds_observation_line, check.occurredOn, check.source, money(check.observedMinor, detail.currencyCode), money(check.differenceMinor, detail.currencyCode))) }
        AccountActions(state, detail, viewModel)
        Text(stringResource(R.string.funds_movements_title), style = MaterialTheme.typography.titleMedium)
    }

}

private fun LazyListScope.accountsOverview(state: FundsUiState, viewModel: FundsViewModel) {
    val input = state.task.input

    item {
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            if (input != null) AppSecondaryButton(stringResource(R.string.funds_resume_task), onClick = viewModel::resume)
            state.overview?.let { summary ->
                Text(stringResource(R.string.funds_net_worth, money(summary.netWorthMinor, summary.homeCurrencyCode)), style = MaterialTheme.typography.headlineSmall)
                Text(stringResource(R.string.funds_assets_liabilities, money(summary.assetsMinor, summary.homeCurrencyCode), money(summary.liabilitiesMinor, summary.homeCurrencyCode)))
                Text(stringResource(R.string.funds_valuation_scope, summary.valuationDate, summary.includedAccounts, summary.unknownAccounts, summary.missingRateAccounts), style = MaterialTheme.typography.bodySmall)
            }
            if (state.access?.canModify == true) AppPrimaryButton(stringResource(R.string.funds_add_account)) { viewModel.start("create") }
            AppSecondaryButton(stringResource(R.string.envelopes_title)) { viewModel.openEnvelopes() }
            if (state.accounts.isEmpty() && !state.loading) Text(stringResource(R.string.funds_empty_accounts))
        }
    }
    items(state.accounts, key = { it.publicId }) { account ->
        AppListRow(onClick = { viewModel.open(account.publicId) }) {
            Column(Modifier.weight(1f)) {
                Text(account.name + (account.tail?.let { " · $it" } ?: ""), style = MaterialTheme.typography.titleSmall)
                Text("${fundKinds()[account.kind]} · ${if (account.visibility == "private") stringResource(R.string.funds_private_visibility) else stringResource(R.string.funds_ledger_visibility)}" +
                    if (account.archived) stringResource(R.string.funds_archived_suffix) else "", style = MaterialTheme.typography.bodySmall)
            }
            Text(account.balanceLabel())
        }
    }

}

@Composable
private fun AccountActions(state: FundsUiState, detail: FinancialAccountDto, viewModel: FundsViewModel) {
    if (detail.canEdit && state.access?.canModify == true) AppSecondaryButton(stringResource(R.string.funds_edit_account)) { viewModel.start("edit") }
    if (detail.kind == "credit" && !detail.archived && state.access?.canModify == true) {
        AppSecondaryButton(stringResource(R.string.funds_incur_fee)) { viewModel.start("incur_fee") }
        AppPrimaryButton(stringResource(R.string.funds_record_actual_repayment)) { viewModel.start("repay") }
    }
    if (!detail.archived && state.access?.canModify == true) {
        if (detail.kind != "credit") listOf("income", "transfer", "loan").forEach { mode ->
            AppSecondaryButton(requireNotNull(fundActions()[mode])) { viewModel.start(mode) }
        }
        if (detail.canEdit) AppSecondaryButton(stringResource(R.string.funds_reconcile)) { viewModel.start("reconciliation") }
    }
    if (detail.kind == "credit") InstallmentHistory(state.installments, !detail.archived && state.access?.canModify == true, viewModel)
}
