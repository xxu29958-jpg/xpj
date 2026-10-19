package com.ticketbox.ui.screens

import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.data.repository.FundsInput
import com.ticketbox.viewmodel.FundsUiState
import com.ticketbox.viewmodel.FundsViewModel

@Composable
internal fun CreditFeeFields(state: FundsUiState, input: FundsInput, enabled: Boolean, vm: FundsViewModel) {
    Text(stringResource(R.string.funds_incur_fee_note))
    FundsField(stringResource(R.string.funds_incurred_amount, input.currency), input.activityAmount, enabled, money = true) { value ->
        vm.edit { it.copy(activityAmount = value) }
    }
    FundsField(stringResource(R.string.funds_fee_source), input.note, enabled) { value -> vm.edit { it.copy(note = value) } }
    Text(if (input.feePeriodId.isEmpty()) stringResource(R.string.funds_fee_no_period) else
        stringResource(R.string.funds_fee_period_selected, input.feePeriodLabel))
    TextButton(enabled = enabled, onClick = { vm.edit { it.copy(feePeriodId = "", feePeriodLabel = "") } }) {
        Text(stringResource(R.string.funds_fee_no_period))
    }
    state.installments?.agreements.orEmpty().filter { it.active }.forEach { agreement ->
        agreement.periods.forEach { period ->
            val label = stringResource(R.string.funds_fee_period_choice, agreement.name, period.position,
                money(period.unincurredFeeMinor, input.currency))
            TextButton(enabled = enabled, onClick = { vm.edit { it.copy(feePeriodId = period.publicId, feePeriodLabel = label) } }) { Text(label) }
        }
    }
}

@Composable
internal fun CreditFeePaymentFields(state: FundsUiState, input: FundsInput, enabled: Boolean, vm: FundsViewModel) {
    val fees = state.detail?.feeObligations.orEmpty().associateBy { it.expenseId.toString() }
    val ids = fees.filterValues { it.remainingMinor > 0 }.keys + input.feePayments.keys
    if (ids.isEmpty()) return
    Text(stringResource(R.string.funds_settle_recorded_fee_note))
    ids.forEach { id ->
        val fee = fees[id]
        Text(fee?.let { stringResource(R.string.funds_fee_owed, it.note, it.occurredOn, money(it.remainingMinor, input.currency)) }
            ?: stringResource(R.string.funds_fee_original_unavailable, id))
        FundsField(stringResource(R.string.funds_fee_settle_amount, input.currency), input.feePayments[id].orEmpty(), enabled, money = true) { value ->
            vm.edit { it.copy(feePayments = if (value.isBlank()) it.feePayments - id else it.feePayments + (id to value)) }
        }
    }
    FundsField(stringResource(R.string.funds_fee_actual_debit, input.payerCurrency), input.payerFeeAmount, enabled, money = true) { value ->
        vm.edit { it.copy(payerFeeAmount = value) }
    }
}
