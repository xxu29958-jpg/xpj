package com.ticketbox.ui.screens.expense.fact

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.selection.toggleable
import androidx.compose.material3.Checkbox
import androidx.compose.material3.minimumInteractiveComponentSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.ExpenseFinancialSummary
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.formatAmountInput
import com.ticketbox.ui.components.AppAmountText
import com.ticketbox.ui.components.AppPaperCard
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.components.parseMinorAmount
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.viewmodel.ExpenseDetailDataLoadState
import com.ticketbox.viewmodel.ExpenseFactUiState
import com.ticketbox.viewmodel.OffsetFormState

internal fun currentOffsetSummary(state: ExpenseFactUiState): ExpenseFinancialSummary? =
    state.factBundle?.financialSummary?.takeIf {
        state.factBundleLoadState == ExpenseDetailDataLoadState.Loaded &&
            state.offsetForm.matchesRoot(state.expense) && state.factBundle.matchesRoot(state.expense)
    }

/** Original-currency arithmetic only. This is not a new home-currency/FX fact. */
internal fun offsetNetPreview(state: ExpenseFactUiState): Long? {
    val form = state.offsetForm
    val expense = form.sourceExpense ?: return null
    val summary = currentOffsetSummary(state) ?: return null
    val rawCode = expense.originalCurrencyCodeRaw ?: expense.originalCurrencyCode.storageKey
    if (!form.kind.isMoneyEvent || rawCode != expense.originalCurrencyCode.storageKey) return null
    val amount = parseMinorAmount(form.amountText, expense.originalCurrencyCode) ?: return null
    return if (amount > 0 && amount <= summary.remainingRefundableOriginalMinor)
        summary.remainingRefundableOriginalMinor - amount else null
}

@Composable
internal fun OffsetImpactPreview(state: ExpenseFactUiState) {
    val net = offsetNetPreview(state) ?: return
    val expense = state.offsetForm.sourceExpense ?: return
    val display = CurrencyDisplay.forRecord(expense.originalCurrencyCode.storageKey)
    val foreign = expense.originalCurrencyCode.storageKey != (expense.homeCurrencyCode ?: expense.homeCurrency.storageKey)
    AppPaperCard(containerColor = LocalThemeVisuals.current.brandPrimaryBg) {
        Column(Modifier.fillMaxWidth().padding(AppSpacing.cardPadding),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
            Text(stringResource(if (foreign) R.string.expense_offset_preview_original else R.string.expense_offset_preview_net,
                expense.originalCurrencyCode.storageKey), style = MaterialTheme.typography.bodyMedium)
            AppAmountText(formatDisplayAmount(net, display), role = AppAmountRole.Hero)
            Text(stringResource(R.string.expense_offset_preview_basis,
                formatDisplayAmount(requireNotNull(currentOffsetSummary(state)).remainingRefundableOriginalMinor, display),
                state.offsetForm.amountText), style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (foreign) Text(stringResource(R.string.expense_offset_preview_fx), style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Composable
internal fun OffsetReversalImpact() {
    AppPaperCard(containerColor = LocalThemeVisuals.current.surfaceApricot) {
        Column(Modifier.padding(AppSpacing.cardPadding), verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            Text(stringResource(R.string.expense_offset_reversal_impact), style = MaterialTheme.typography.titleMedium)
            Text(stringResource(R.string.expense_offset_reversal_explainer), style = MaterialTheme.typography.bodyMedium)
        }
    }
}

@Composable
internal fun OffsetReversalReview(reviewed: Boolean, enabled: Boolean, onReviewed: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth().minimumInteractiveComponentSize()
        .toggleable(reviewed, enabled = enabled, role = Role.Checkbox, onValueChange = onReviewed),
        verticalAlignment = Alignment.CenterVertically) {
        Checkbox(checked = reviewed, onCheckedChange = null, enabled = enabled)
        Text(stringResource(R.string.expense_offset_reversal_review), style = MaterialTheme.typography.bodyMedium)
    }
}

/** Input error and remaining-balance text shared by the offset sheet. */
@Composable
internal fun offsetFieldErrorText(error: UiText?): (@Composable () -> Unit)? {
    val text = error ?: return null
    return {
        Text(
            text = text.asString(),
            color = MaterialTheme.colorScheme.error,
            style = MaterialTheme.typography.bodySmall,
        )
    }
}

@Composable
internal fun offsetAmountSupportingText(
    form: OffsetFormState,
    summary: ExpenseFinancialSummary?,
    currency: CurrencyCode,
): (@Composable () -> Unit)? {
    offsetFieldErrorText(form.amountError)?.let { return it }
    val hint = if (summary != null) {
        stringResource(
            R.string.expense_offset_remaining_hint,
            formatAmountInput(summary.remainingRefundableOriginalMinor, currency),
        )
    } else {
        stringResource(R.string.expense_offset_remaining_unavailable)
    }
    return {
        Text(
            text = hint,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
    }
}
