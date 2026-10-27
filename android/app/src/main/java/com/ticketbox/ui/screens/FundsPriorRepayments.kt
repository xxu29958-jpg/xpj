package com.ticketbox.ui.screens

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.FinancialAccount
import com.ticketbox.data.repository.FundsInput
import com.ticketbox.viewmodel.FundsViewModel
import com.ticketbox.viewmodel.voidPayment

@Composable
internal fun FundsPriorRepayments(detail: FinancialAccount, canModify: Boolean, vm: FundsViewModel) {
    val prior = detail.priorRepayments?.takeIf { it.items.isNotEmpty() } ?: return
    Text(stringResource(R.string.funds_prior_repayments), style = MaterialTheme.typography.titleMedium)
    prior.items.forEach { row ->
        Text(money(row.originalAmountMinor ?: row.amountCents, row.originalCurrencyCode ?: prior.homeCurrencyCode))
        Text(stringResource(R.string.funds_prior_recorded_at, row.createdAt), style = MaterialTheme.typography.bodySmall)
        if (row.voidFact != null) Text(stringResource(R.string.funds_credit_voided, row.voidFact.reason))
        else if (detail.canEdit && canModify) TextButton(onClick = { vm.voidPayment(row.publicId) }) {
            Text(stringResource(R.string.funds_void_prior_repayment))
        }
    }
}

@Composable
internal fun FundsVoidPaymentFields(input: FundsInput, enabled: Boolean, vm: FundsViewModel) {
    Text(stringResource(if (input.legacyRepayment) R.string.funds_void_prior_note else R.string.funds_void_payment_note))
    if (input.legacyRepayment) {
        FundsField(stringResource(R.string.funds_reviewed_debt, input.currency), input.reviewedDebtAmount, enabled, money = true) {
            value -> vm.edit { it.copy(reviewedDebtAmount = value) }
        }
        Text(stringResource(R.string.funds_reviewed_debt_note), style = MaterialTheme.typography.bodySmall)
    }
    FundsField(stringResource(R.string.funds_void_reason), input.note, enabled) { value -> vm.edit { it.copy(note = value) } }
}
