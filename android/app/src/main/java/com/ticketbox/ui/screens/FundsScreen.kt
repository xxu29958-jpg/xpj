package com.ticketbox.ui.screens

import com.ticketbox.ui.asString
import com.ticketbox.R
import com.ticketbox.viewmodel.openEnvelopes
import androidx.compose.ui.res.stringResource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import com.ticketbox.domain.model.FinancialAccount
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.components.AppFloatingActionBar
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryPageSlots
import com.ticketbox.ui.components.AppSecondaryRefreshState
import com.ticketbox.ui.components.AppSecondaryScrollableContent
import com.ticketbox.presentation.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.viewmodel.FundsUiState
import com.ticketbox.viewmodel.FundsViewModel
import com.ticketbox.viewmodel.start
import com.ticketbox.viewmodel.voidPayment
import com.ticketbox.viewmodel.voidActivity

@Composable
internal fun fundKinds() = linkedMapOf("cash" to stringResource(R.string.funds_kind_cash), "bank" to stringResource(R.string.funds_kind_bank), "wallet" to stringResource(R.string.funds_kind_wallet), "credit" to stringResource(R.string.funds_kind_credit))
@Composable
internal fun fundActions() = mapOf("create" to stringResource(R.string.funds_add_account), "edit" to stringResource(R.string.funds_edit_account), "repay" to stringResource(R.string.funds_record_repayment),
    "incur_fee" to stringResource(R.string.funds_incur_fee),
    "apply_credit" to stringResource(R.string.funds_apply_credit), "void_credit" to stringResource(R.string.funds_void_credit),
    "void_repayment" to stringResource(R.string.funds_void_payment),
    "void_activity" to stringResource(R.string.funds_void_activity),
    "envelopes" to stringResource(R.string.envelopes_edit),
    "income" to stringResource(R.string.funds_record_income), "loan" to stringResource(R.string.funds_record_loan), "transfer" to stringResource(R.string.funds_record_transfer), "reconciliation" to stringResource(R.string.funds_reconcile), "funding" to stringResource(R.string.funds_funding_title), "installments" to stringResource(R.string.funds_record_installments))
internal fun money(value: Long, currency: String) = formatDisplayAmount(value, CurrencyDisplay.forRecord(currency))

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
        slots = AppSecondaryPageSlots(bottomBar = fundsBottomAction(state, viewModel)),
    ) {
        state.pageError()?.let { message -> item { Text(message.asString(), color = MaterialTheme.colorScheme.error) } }
        if (state.fromCache) item { Text(stringResource(R.string.funds_cached_note), style = MaterialTheme.typography.bodySmall) }
        when {
            state.editing && input != null -> item { FundsEditor(state, input, viewModel) }
            state.envelopeMonth != null -> item { EnvelopeOverview(state, viewModel) }
            state.fundingPage -> item { FundingReadPanel(state, viewModel) }
            state.captureRequested -> captureAccounts(state, viewModel)
            detail != null -> accountDetail(state, detail, viewModel, onExpense)
            else -> fundsOverview(state, FundsOverviewActions(open = { viewModel.open(it) }, create = { viewModel.start("create") },
                envelopes = { month -> if (month == null) viewModel.openEnvelopes() else viewModel.openEnvelopes(month) }, resume = viewModel::resume))
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

/**
 * An open editor keeps its confirm in the bar, above the keyboard while an amount is typed.
 * Adding an account stays reachable at the bottom of a filled overview; the empty state carries its own.
 */
private fun fundsBottomAction(state: FundsUiState, viewModel: FundsViewModel): (@Composable () -> Unit)? {
    val input = state.task.input
    if (state.editing && input != null) return { AppFloatingActionBar { FundsSubmission(state, input, viewModel) } }
    val overview = !state.editing && state.envelopeMonth == null && !state.fundingPage && !state.captureRequested && state.detail == null
    if (!overview || state.accounts.isEmpty() || state.access?.canModify != true) return null
    return { AppFloatingActionBar { AppPrimaryButton(stringResource(R.string.funds_add_account), modifier = Modifier.fillMaxWidth()) { viewModel.start("create") } } }
}

private fun LazyListScope.accountDetail(state: FundsUiState, detail: FinancialAccount, viewModel: FundsViewModel, onExpense: (Long) -> Unit) {
    val canModify = state.access?.canModify == true
    item { AccountDetailHeader(state, detail, viewModel) }
    if (detail.feeObligations.isNotEmpty()) item {
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
            Text(stringResource(R.string.funds_fee_obligations_title), style = MaterialTheme.typography.titleMedium)
            Text(stringResource(R.string.funds_fee_obligations_note), style = MaterialTheme.typography.bodySmall)
        }
    }
    items(detail.feeObligations, key = { "fee:${it.expenseId}" }) { fee ->
        FundsIconRow(FundsRowModel(R.drawable.ic_lucide_receipt_text, fee.note, fee.occurredOn,
            stringResource(R.string.funds_fee_remaining, money(fee.remainingMinor, detail.currencyCode))), onClick = null,
            iconBackground = LocalThemeVisuals.current.surfaceApricot) {
            FundsRowLink(stringResource(R.string.funds_view_fee_expense)) { onExpense(fee.expenseId) }
        }
    }
    item { AccountDetailRecords(state, detail, viewModel) }
    val actions = FundsMovementActions(
        openExpense = onExpense,
        voidActivity = if (canModify) { row -> viewModel.voidActivity(row) } else null,
        voidPayment = if (canModify) { id -> viewModel.voidPayment(id) } else null,
        reconcile = if (canModify && detail.canEdit && !detail.archived) { { viewModel.start("reconciliation") } } else null,
    )
    items(detail.movements, key = { it.publicId }) { row -> FundsMovementRow(row, detail, actions) }
    if (detail.movements.isEmpty()) item { Text(stringResource(R.string.funds_movements_empty), style = MaterialTheme.typography.bodySmall) }
}

@Composable
private fun AccountDetailHeader(state: FundsUiState, detail: FinancialAccount, viewModel: FundsViewModel) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        FundsHeroCard(label = stringResource(detail.balanceLabelRes()), amount = detail.balanceText()) {
            Text(stringResource(R.string.funds_account_meta, fundKinds()[detail.kind].orEmpty(), detail.currencyCode,
                stringResource(if (detail.visibility == "private") R.string.funds_private_visibility else R.string.funds_ledger_visibility)) +
                (detail.tail?.let { stringResource(R.string.funds_tail_suffix, it) } ?: ""), style = MaterialTheme.typography.bodySmall)
            if (detail.unallocatedCreditMinor > 0) Text(stringResource(R.string.funds_unallocated_credit_note, money(detail.unallocatedCreditMinor, detail.currencyCode)),
                style = MaterialTheme.typography.bodySmall)
            if (detail.balanceMinor == null) Text(stringResource(R.string.funds_recorded_change_note, money(detail.recordedChangeMinor, detail.currencyCode)),
                style = MaterialTheme.typography.bodySmall)
            detail.observation?.let { check -> Text(stringResource(R.string.funds_observation_line, check.occurredOn, check.source,
                money(check.observedMinor, detail.currencyCode), money(check.differenceMinor, detail.currencyCode)), style = MaterialTheme.typography.bodySmall) }
        }
        AccountActions(state, detail, viewModel)
        AccountMore(state, detail, viewModel)
    }
}

@Composable
private fun AccountDetailRecords(state: FundsUiState, detail: FinancialAccount, viewModel: FundsViewModel) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        CreditApplicationsRead(detail, state.access?.canModify == true, viewModel)
        FundsPriorRepayments(detail, state.access?.canModify == true, viewModel)
        if (!state.installments?.agreements.isNullOrEmpty())
            InstallmentHistory(state.installments, !detail.archived && state.access?.canModify == true, viewModel)
        Text(stringResource(R.string.funds_movements_title), modifier = Modifier.padding(top = AppSpacing.compactGap),
            style = MaterialTheme.typography.titleMedium)
    }
}

private fun FinancialAccount.balanceLabelRes(): Int = when {
    kind != "credit" -> R.string.funds_balance_current
    balanceMinor != null && balanceMinor > 0 -> R.string.funds_balance_surplus
    else -> R.string.funds_balance_debt
}
