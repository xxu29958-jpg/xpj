package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import com.ticketbox.R
import com.ticketbox.data.repository.FundsInput
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalThemeVisuals
import org.json.JSONArray

/** Restates what confirming will change, in the person's own numbers, beside the confirm button. The server still decides the result. */
@Composable
internal fun FundsChangeSummary(input: FundsInput, purposeLabels: Map<String, String>) {
    val text = fundsChangeSentence(input, purposeLabels) ?: return
    Surface(shape = RoundedCornerShape(AppRadius.medium), color = LocalThemeVisuals.current.surfaceSand,
        modifier = Modifier.fillMaxWidth().semantics { liveRegion = LiveRegionMode.Polite }) {
        Text(text, modifier = Modifier.padding(AppSpacing.compactPadding), style = MaterialTheme.typography.bodyMedium)
    }
}

/** The same sentences as the web task form, so both clients explain a change in the same words. */
@Composable
internal fun fundsChangeSentence(input: FundsInput, purposeLabels: Map<String, String>): String? = when (input.mode) {
    "create" -> input.name.present()?.let { createSentence(input) }
    "income", "loan", "transfer", "reconciliation" -> input.activityAmount.present()?.let { activitySentence(input, it) }
    "installments" -> installmentSentence(input)
    "repay" -> repaySentence(input)
    "envelopes" -> envelopeSentence(input, purposeLabels)
    else -> null
}

@Composable
private fun activitySentence(input: FundsInput, value: String): String? = when (input.mode) {
    "income" -> stringResource(R.string.funds_preview_income, input.name, amount(value, input.currency))
    "loan" -> input.loanPrincipal.present()?.let { principal -> stringResource(R.string.funds_preview_loan, input.name, amount(value, input.currency),
        input.loanName.present() ?: stringResource(R.string.funds_preview_loan_default), amount(principal, input.loanCurrency)) }
    "transfer" -> input.payerId.takeIf { it.isNotBlank() }?.let { stringResource(R.string.funds_preview_transfer, input.name, amount(value, input.currency),
        input.payerName, amount(input.otherAmount.present() ?: "—", input.payerCurrency)) }
    else -> stringResource(if (input.applyAdjustment) R.string.funds_preview_reconcile_adjust else R.string.funds_preview_reconcile_snapshot,
        amount(value, input.currency))
}

@Composable
private fun createSentence(input: FundsInput): String {
    val opening = input.opening.present()?.let { value -> stringResource(
        if (input.kind == "credit") R.string.funds_preview_opening_debt else R.string.funds_preview_opening_balance, amount(value, input.currency), input.date) }
        ?: stringResource(R.string.funds_preview_opening_unknown)
    val audience = stringResource(if (input.visibility == "ledger") R.string.funds_preview_ledger else R.string.funds_preview_private)
    return stringResource(R.string.funds_preview_create, fundKinds()[input.kind].orEmpty(), input.name, input.currency, opening, audience)
}

@Composable
private fun repaySentence(input: FundsInput): String? {
    val principal = input.principal.present()?.takeIf { input.payerId.isNotBlank() } ?: return null
    val parts = listOfNotNull(
        stringResource(R.string.funds_preview_part_principal, amount(input.paid.present() ?: principal, input.payerCurrency)),
        input.newFee.present()?.let { stringResource(R.string.funds_preview_part_new_fee, amount(it, input.payerCurrency)) },
        input.payerFeeAmount.present()?.let { stringResource(R.string.funds_preview_part_recorded_fee, amount(it, input.payerCurrency)) },
    )
    val overpayment = input.overpayment.present()?.let { stringResource(R.string.funds_preview_overpayment, amount(it, input.currency)) }.orEmpty()
    val feeExpense = if (input.newFee.present() != null) stringResource(R.string.funds_preview_new_fee_expense) else ""
    return stringResource(R.string.funds_preview_repay, input.payerName, parts.joinToString("，"), input.name, amount(principal, input.currency),
        overpayment + stringResource(R.string.funds_preview_repay_tail, feeExpense))
}

@Composable
private fun installmentSentence(input: FundsInput): String? {
    val periods = runCatching { JSONArray(input.periodsJson).length() }.getOrDefault(0)
    val name = input.name.present()?.takeIf { periods > 0 } ?: return null
    return stringResource(R.string.funds_preview_installments, name, input.drawIds.size, periods)
}

@Composable
private fun envelopeSentence(input: FundsInput, labels: Map<String, String>): String {
    val parts = input.envelopeAmounts.mapNotNull { (purpose, value) ->
        value.present()?.takeIf { it.toBigDecimalOrNull()?.signum() != 0 }?.let { "${labels[purpose] ?: purpose.removePrefix("category:")} $it" }
    }
    return if (parts.isEmpty()) stringResource(R.string.envelopes_preview_none, input.envelopeMonth)
    else stringResource(R.string.envelopes_preview, input.envelopeMonth, parts.joinToString("、"), input.currency)
}

private fun String.present(): String? = trim().takeIf { it.isNotEmpty() }

private fun amount(value: String, currency: String) = "$value $currency"
