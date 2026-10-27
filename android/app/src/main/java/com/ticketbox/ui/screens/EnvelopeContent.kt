package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import com.ticketbox.R
import com.ticketbox.domain.model.EnvelopePurpose
import com.ticketbox.data.repository.FundsInput
import com.ticketbox.ui.components.AppHistoryRecord
import com.ticketbox.presentation.displayDateTime
import com.ticketbox.ui.components.AppListRow
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSwitch
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.FundsUiState
import com.ticketbox.viewmodel.FundsViewModel
import com.ticketbox.viewmodel.openEnvelopes
import com.ticketbox.viewmodel.startEnvelope
import com.ticketbox.viewmodel.loadEnvelopeHistory
import com.ticketbox.viewmodel.useEnvelopePlan
import java.time.YearMonth

@Composable
private fun envelopeMoney(value: Long?, currency: String): String = value?.let { money(it, currency) }
    ?: stringResource(R.string.envelopes_unknown)

@Composable
internal fun EnvelopeOverview(state: FundsUiState, vm: FundsViewModel) {
    val month = state.envelopeMonth ?: return
    val current = YearMonth.parse(month)
    val view = state.envelopes
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap), verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = { vm.openEnvelopes(current.minusMonths(1).toString()) }) { Text(stringResource(R.string.envelopes_previous_month)) }
            Text(displayMonthLabel(month), modifier = Modifier.weight(1f), style = MaterialTheme.typography.titleMedium, textAlign = TextAlign.Center)
            TextButton(onClick = { vm.openEnvelopes(current.plusMonths(1).toString()) }) { Text(stringResource(R.string.envelopes_next_month)) }
        }
        view?.let {
            FundsHeroCard(label = stringResource(if ((it.unassignedMinor ?: 0) < 0) R.string.envelopes_shortfall else R.string.envelopes_unassigned),
                amount = envelopeMoney(it.unassignedMinor?.let { value -> kotlin.math.abs(value) }, it.homeCurrencyCode)) {
                Text(stringResource(R.string.envelopes_cash_scope, envelopeMoney(it.cashMinor, it.homeCurrencyCode),
                    envelopeMoney(it.reservedMinor, it.homeCurrencyCode), it.valuationDate), style = MaterialTheme.typography.bodySmall)
                Text(stringResource(R.string.envelopes_explanation), style = MaterialTheme.typography.bodySmall)
            }
            if (state.access?.canModify == true)
                AppPrimaryButton(stringResource(R.string.envelopes_edit), modifier = Modifier.fillMaxWidth(), onClick = vm::startEnvelope)
            it.notices.forEach { message -> Text(message, color = MaterialTheme.colorScheme.error) }
            it.purposes.forEach { row -> AppListRow { EnvelopePurpose(row, it.homeCurrencyCode) } }
        }
        Text(stringResource(R.string.envelopes_rollover_note), style = MaterialTheme.typography.bodySmall)
        EnvelopeHistory(state, vm)
    }
}

@Composable
private fun EnvelopePurpose(row: EnvelopePurpose, currency: String) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        Text(row.label, style = MaterialTheme.typography.titleMedium)
        Text(row.plannedMinor?.let { stringResource(R.string.envelopes_plan, money(it, currency)) }
            ?: stringResource(R.string.envelopes_plan_unavailable))
        if (row.funded) Text(stringResource(R.string.envelopes_purpose_balance,
            envelopeMoney(row.availableMinor, currency), envelopeMoney(row.reservedMinor, currency)))
        else Text(stringResource(R.string.envelopes_not_funded))
        if ((row.unpaidCreditMinor ?: 0) > 0) Text(stringResource(R.string.envelopes_unpaid,
            envelopeMoney(row.unpaidCreditMinor, currency)), style = MaterialTheme.typography.bodySmall)
        if ((row.unlinkedMinor ?: 0) > 0) Text(stringResource(R.string.envelopes_unlinked,
            envelopeMoney(row.unlinkedMinor, currency)), style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
internal fun EnvelopeFields(state: FundsUiState, input: FundsInput, enabled: Boolean, vm: FundsViewModel) {
    val view = state.envelopes?.takeIf { it.month == input.envelopeMonth }
    Text(stringResource(R.string.envelopes_period_currency, displayMonthLabel(input.envelopeMonth), input.currency))
    val chosen = input.envelopeAccounts.size
    // Which accounts supply the cash rarely changes month to month, so it stays folded once chosen.
    FundsOptions(stringResource(R.string.envelopes_sources_title),
        filled = if (chosen > 0) stringResource(R.string.envelopes_sources_chosen, chosen) else null,
        empty = stringResource(R.string.envelopes_sources_none)) {
        Text(stringResource(R.string.envelopes_sources_note), style = MaterialTheme.typography.bodySmall)
        view?.accounts?.forEach { account ->
            AppListRow {
                Column(Modifier.weight(1f)) {
                    Text(account.name)
                    Text(envelopeMoney(account.balanceMinor, account.currencyCode), style = MaterialTheme.typography.bodySmall)
                }
                AppSwitch(checked = account.publicId in input.envelopeAccounts, enabled = enabled && account.canSelect,
                    contentDescription = account.name, onCheckedChange = { checked -> vm.edit {
                        it.copy(envelopeAccounts = if (checked) (it.envelopeAccounts + account.publicId).distinct()
                            else it.envelopeAccounts - account.publicId)
                    } })
            }
        }
        if (view?.accounts?.isEmpty() == true) Text(stringResource(R.string.envelopes_no_accounts))
    }
    val labels = view?.purposes.orEmpty().associate { it.purpose to it.label }
    if (view?.purposes?.any { it.plannedMinor != null } == true)
        TextButton(onClick = vm::useEnvelopePlan, enabled = enabled) { Text(stringResource(R.string.envelopes_fill_plan)) }
    input.envelopeAmounts.forEach { (purpose, amount) ->
        FundsField(stringResource(R.string.envelopes_assignment_label, labels[purpose] ?: retainedPurpose(purpose), input.currency),
            amount, enabled, money = true) { value -> vm.edit { it.copy(envelopeAmounts = it.envelopeAmounts + (purpose to value)) } }
    }
    Text(stringResource(R.string.envelopes_input_note), style = MaterialTheme.typography.bodySmall)
    FundsField(stringResource(R.string.envelopes_reason), input.note, enabled) { value -> vm.edit { it.copy(note = value) } }
}

@Composable
internal fun retainedPurpose(purpose: String) = when (purpose) {
    "spending" -> stringResource(R.string.envelopes_other_spending)
    "savings" -> stringResource(R.string.envelopes_savings)
    "buffer" -> stringResource(R.string.envelopes_buffer)
    else -> purpose.removePrefix("category:")
}

@Composable
private fun EnvelopeHistory(state: FundsUiState, vm: FundsViewModel) {
    if (state.envelopeHistory == null || state.envelopeHistoryMore) {
        TextButton(onClick = vm::loadEnvelopeHistory, enabled = !state.envelopeHistoryBusy) {
            Text(stringResource(if (state.envelopeHistory == null) R.string.envelopes_history else R.string.envelopes_older_history))
        }
    }
    state.envelopeHistory?.let { rows ->
        if (rows.isEmpty()) Text(stringResource(R.string.envelopes_history_empty))
        rows.forEach { row ->
            AppHistoryRecord(title = stringResource(R.string.envelopes_history_version, row.rowVersion),
                recordedAt = displayDateTime(row.recordedAt), summary = {
                    Text(stringResource(R.string.envelopes_history_reason, displayMonthLabel(row.month), row.reason))
                }) {
                    row.allocationSnapshot.allocations.forEach { (purpose, amount) ->
                        Text(stringResource(R.string.envelopes_history_amount, retainedPurpose(purpose),
                            money(amount, row.allocationSnapshot.homeCurrencyCode)), style = MaterialTheme.typography.bodySmall)
                    }
            }
        }
    }
}
