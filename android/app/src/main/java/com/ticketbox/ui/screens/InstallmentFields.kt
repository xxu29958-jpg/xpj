package com.ticketbox.ui.screens

import com.ticketbox.R
import androidx.compose.ui.res.stringResource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.material3.Checkbox
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import com.ticketbox.data.remote.dto.InstallmentsDto
import com.ticketbox.data.repository.FundsInput
import com.ticketbox.data.repository.InstallmentInputWire
import com.ticketbox.data.repository.InstallmentPeriodInput
import com.ticketbox.data.repository.CreditAllocationInput
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.FundsViewModel
import com.ticketbox.viewmodel.start
import com.ticketbox.viewmodel.reviseAgreement

private fun amount(value: Long, currency: String) = formatDisplayAmount(value, CurrencyDisplay.forRecord(currency))

@Composable
internal fun InstallmentFields(input: FundsInput, data: InstallmentsDto?, enabled: Boolean, vm: FundsViewModel) {
    Text(stringResource(R.string.funds_installment_note))
    FundsField(stringResource(R.string.funds_agreement_name), input.name, enabled) { value -> vm.edit { it.copy(name = value) } }
    FundsField(stringResource(R.string.funds_agreement_source), input.source, enabled) { value -> vm.edit { it.copy(source = value) } }
    Text(stringResource(R.string.funds_select_draws), style = MaterialTheme.typography.titleSmall)
    data?.draws.orEmpty().filter { it.remainingMinor > 0 && (it.agreementPublicId == null || it.agreementPublicId == input.previousAgreement) }.forEach { draw ->
        Row {
            Checkbox(draw.publicId in input.drawIds, { chosen -> vm.edit { it.copy(drawIds = if (chosen) it.drawIds + draw.publicId else it.drawIds - draw.publicId) } }, enabled = enabled)
            Text(stringResource(R.string.funds_draw_line, draw.note, draw.occurredOn, amount(draw.remainingMinor, input.currency)))
        }
    }
    Text(stringResource(R.string.funds_periods_title, input.currency), style = MaterialTheme.typography.titleSmall)
    val periods = InstallmentInputWire.periods.fromJson(input.periodsJson).orEmpty()
    periods.forEachIndexed { index, row ->
        fun put(value: InstallmentPeriodInput) = vm.edit { it.copy(periodsJson = InstallmentInputWire.periods.toJson(
            periods.toMutableList().also { rows -> rows[index] = value })) }
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            FundsField(stringResource(R.string.funds_period_due, index + 1), row.date, enabled) { put(row.copy(date = it)) }
            FundsField(stringResource(R.string.funds_period_principal), row.principal, enabled, money = true) { put(row.copy(principal = it)) }
            FundsField(stringResource(R.string.funds_planned_fee), row.fee, enabled, money = true) { put(row.copy(fee = it)) }
            TextButton(onClick = { vm.edit { it.copy(periodsJson = InstallmentInputWire.periods.toJson(periods.filterIndexed { n, _ -> n != index })) } }, enabled = enabled) { Text(stringResource(R.string.funds_remove_period)) }
        }
    }
    AppSecondaryButton(stringResource(R.string.funds_add_period), enabled = enabled && periods.size < 120) { vm.edit {
        it.copy(periodsJson = InstallmentInputWire.periods.toJson(periods + InstallmentPeriodInput())) } }
    Text(stringResource(R.string.funds_revision_note), style = MaterialTheme.typography.bodySmall)
    Text(stringResource(R.string.funds_fee_only_schedule), style = MaterialTheme.typography.bodySmall)
}

@Composable
internal fun InstallmentPaymentFields(input: FundsInput, data: InstallmentsDto?, enabled: Boolean, vm: FundsViewModel) {
    val allocations = InstallmentInputWire.allocations.fromJson(input.allocationJson).orEmpty()
    fun put(value: CreditAllocationInput) = vm.edit { it.copy(allocationJson = InstallmentInputWire.allocations.toJson(
        allocations.filter { row -> row.id != value.id } + value)) }
    Text(stringResource(R.string.funds_allocation_title, input.currency), style = MaterialTheme.typography.titleSmall)
    Text(stringResource(R.string.funds_allocation_note))
    val validIds = mutableSetOf<String>()
    data?.agreements.orEmpty().filter { it.active }.forEach { agreement ->
        Text(stringResource(R.string.funds_agreement_version, agreement.name, agreement.revision))
        if (agreement.needsReview) Text(stringResource(R.string.funds_replan_required), color = MaterialTheme.colorScheme.error)
        agreement.periods.filter { it.principalMinor > it.paidPrincipalMinor || it.unincurredFeeMinor > 0 }.forEach { period ->
            validIds.add(period.publicId)
            val row = allocations.firstOrNull { it.id == period.publicId } ?: CreditAllocationInput(period.publicId, "period")
            Text(stringResource(R.string.funds_outstanding_period, period.position, period.dueOn, amount(period.principalMinor - period.paidPrincipalMinor, input.currency)))
            Text(stringResource(R.string.funds_remaining_period_fee, amount(period.unincurredFeeMinor, input.currency)))
            FundsField(stringResource(R.string.funds_principal_payment), row.principal, enabled, money = true) { put(row.copy(principal = it)) }
            FundsField(stringResource(R.string.funds_new_period_fee), row.fee, enabled, money = true) { put(row.copy(fee = it)) }
        }
    }
    data?.draws.orEmpty().filter { it.agreementPublicId == null && it.remainingMinor > 0 }.forEach { draw ->
        validIds.add(draw.publicId)
        val row = allocations.firstOrNull { it.id == draw.publicId } ?: CreditAllocationInput(draw.publicId, "draw")
        Text(stringResource(R.string.funds_unplanned_draw, draw.note, amount(draw.remainingMinor, input.currency)))
        FundsField(stringResource(R.string.funds_settle_draw), row.principal, enabled, money = true) { put(row.copy(principal = it)) }
    }
    allocations.filter { it.id !in validIds && (it.principal.isNotBlank() || it.fee.isNotBlank()) }.forEach { row ->
        Text(stringResource(R.string.funds_missing_allocation, row.principal, row.fee))
        TextButton(onClick = { vm.edit { it.copy(allocationJson = InstallmentInputWire.allocations.toJson(allocations - row)) } }, enabled = enabled) { Text(stringResource(R.string.funds_remove_allocation)) }
    }
    FundsField(stringResource(R.string.funds_overpayment), input.overpayment, enabled, money = true) { value -> vm.edit { it.copy(overpayment = value) } }
}

@Composable
internal fun InstallmentHistory(data: InstallmentsDto?, canModify: Boolean, vm: FundsViewModel) {
    Text(stringResource(R.string.funds_installment_title), style = MaterialTheme.typography.titleMedium)
    if (canModify) AppSecondaryButton(stringResource(R.string.funds_add_agreement)) { vm.start("installments") }
    data?.agreements.orEmpty().forEach { agreement ->
        Text(stringResource(R.string.funds_agreement_summary, agreement.name, agreement.revision, if (agreement.active) stringResource(R.string.funds_active_agreement) else stringResource(R.string.funds_history_agreement)))
        Text("${agreement.agreedOn} · ${agreement.source}", style = MaterialTheme.typography.bodySmall)
        if (agreement.needsReview) Text(stringResource(R.string.funds_revised_principal_note))
        if (agreement.periods.isEmpty()) Text(stringResource(R.string.funds_no_remaining_periods))
        agreement.periods.forEach { period ->
            Text(stringResource(R.string.funds_period_history, period.position, period.dueOn, amount(period.principalMinor, data!!.currencyCode), amount(period.paidPrincipalMinor, data.currencyCode), amount(period.plannedFeeMinor, data.currencyCode), amount(period.paidFeeMinor, data.currencyCode)))
            period.incurredFeeMinor?.let { Text(stringResource(R.string.funds_period_incurred_fee, amount(it, data.currencyCode))) }
        }
        if (agreement.active && canModify) AppSecondaryButton(stringResource(R.string.funds_replan)) { vm.reviseAgreement(agreement) }
    }
}
