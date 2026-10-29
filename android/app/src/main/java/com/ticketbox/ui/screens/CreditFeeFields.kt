package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.data.repository.FundsInput
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.FundsUiState
import com.ticketbox.viewmodel.FundsViewModel

@Composable
internal fun CreditFeeFields(state: FundsUiState, input: FundsInput, enabled: Boolean, vm: FundsViewModel) {
    Text(stringResource(R.string.funds_incur_fee_note))
    FundsField(stringResource(R.string.funds_incurred_amount, input.currency), input.activityAmount, enabled, money = true) { value ->
        vm.edit { it.copy(activityAmount = value) }
    }
    FundsField(stringResource(R.string.funds_fee_source), input.note, enabled) { value -> vm.edit { it.copy(note = value) } }
    val none = stringResource(R.string.funds_fee_no_period)
    Text(stringResource(R.string.funds_fee_period_selected, input.feePeriodLabel.ifEmpty { none }))
    // The choices show which one is chosen, so the line above reads as a label rather than a repeated option.
    FlowRow(horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        FilterChip(input.feePeriodId.isEmpty(), { vm.edit { it.copy(feePeriodId = "", feePeriodLabel = "") } }, { Text(none) }, enabled = enabled)
        state.installments?.agreements.orEmpty().filter { it.active }.forEach { agreement ->
            agreement.periods.forEach { period ->
                val label = stringResource(R.string.funds_fee_period_choice, agreement.name, period.position,
                    money(period.unincurredFeeMinor, input.currency))
                FilterChip(input.feePeriodId == period.publicId, { vm.edit { it.copy(feePeriodId = period.publicId, feePeriodLabel = label) } },
                    { Text(label) }, enabled = enabled)
            }
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
