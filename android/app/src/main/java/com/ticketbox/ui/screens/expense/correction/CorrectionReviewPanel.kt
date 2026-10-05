package com.ticketbox.ui.screens.expense.correction

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.selection.selectable
import androidx.compose.material3.RadioButton
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.Role
import com.ticketbox.ui.components.AppContentCard
import com.ticketbox.ui.components.AppValueComparison
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.CorrectionReviewField
import com.ticketbox.viewmodel.CorrectionReviewSelection
import com.ticketbox.viewmodel.CorrectionScalarComparison
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.components.AppSectionHeader
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.viewmodel.ExpenseFactUiState
import com.ticketbox.viewmodel.FactCorrectionReview

@Composable
internal fun CorrectionReviewPanel(review: FactCorrectionReview, state: ExpenseFactUiState,
    adopt: (CorrectionReviewSelection) -> Unit, refresh: () -> Unit) {
    var keepItems by remember(review) { mutableStateOf<Boolean?>(null) }
    var keepSplits by remember(review) { mutableStateOf<Boolean?>(null) }
    var scalarChoices by remember(review.current.rowVersion) { mutableStateOf(emptyMap<CorrectionReviewField, Boolean>()) }
    AppSectionHeader(title = stringResource(R.string.expense_correction_review_title))
    val current = review.current
    Text(stringResource(R.string.expense_correction_review_versions, review.original.rowVersion, current.rowVersion),
        style = MaterialTheme.typography.bodySmall)
    review.scalars.forEach { row ->
        CorrectionComparison(row)
        if (row.conflict) ReviewChoice(scalarChoices[row.field]) { scalarChoices = scalarChoices + (row.field to it) }
    }
    Text(stringResource(R.string.expense_correction_review_explainer), style = MaterialTheme.typography.bodySmall)
    if (review.itemsChoiceRequired) {
        val currentRows = state.expenseItems?.items.orEmpty().joinToString("\n") { "${it.name} · ${it.kind} · ${homeAmount(it.amountCents, current)}" }
        val originalRows = state.correction.itemDrafts.joinToString("\n") { "${it.name} · ${it.kind} · ${it.amountText}" }
        CollectionReviewChoice(stringResource(R.string.expense_correction_items_entry), currentRows, originalRows, keepItems) { keepItems = it }
    }
    if (review.splitsChoiceRequired) {
        val currentRows = state.expenseSplits?.splits.orEmpty().joinToString("\n") { "${it.accountName} · ${homeAmount(it.amountCents, current)} · ${it.note.orEmpty()}" }
        val originalRows = state.correction.splitDrafts.filter { it.included }.joinToString("\n") { "${it.displayName} · ${it.amountText}" }
        CollectionReviewChoice(stringResource(R.string.expense_correction_splits_entry), currentRows, originalRows, keepSplits) { keepSplits = it }
    }
    AppPrimaryButton(text = stringResource(R.string.expense_correction_review_adopt),
        modifier = Modifier.fillMaxWidth(),
        onClick = { adopt(CorrectionReviewSelection(current.rowVersion, scalarChoices, keepItems, keepSplits)) },
        enabled = review.ready && review.scalars.none { it.conflict && it.field !in scalarChoices } &&
            (!review.itemsChoiceRequired || keepItems != null) && (!review.splitsChoiceRequired || keepSplits != null))
    TextButton(onClick = refresh, enabled = !state.expenseLoading && !state.itemsLoading && !state.splitsLoading) {
        Text(stringResource(R.string.expense_fact_refresh_current))
    }
}

@Composable
internal fun CorrectionComparison(row: CorrectionScalarComparison) {
    val label = when (row.field) {
        CorrectionReviewField.Money -> R.string.expense_edit_amount_field_label
        CorrectionReviewField.Time -> R.string.correction_field_time
        CorrectionReviewField.Merchant -> R.string.correction_field_merchant
        CorrectionReviewField.Category -> R.string.correction_field_category
        CorrectionReviewField.Tags -> R.string.correction_field_tags
        CorrectionReviewField.Note -> R.string.correction_field_note
        CorrectionReviewField.ValueScore -> R.string.correction_field_value
        CorrectionReviewField.RegretScore -> R.string.correction_field_regret
    }
    AppContentCard {
        Text(stringResource(label), style = MaterialTheme.typography.titleMedium)
        AppValueComparison(stringResource(R.string.expense_correction_comparison_current), row.current.ifBlank { "—" },
            stringResource(R.string.expense_correction_comparison_proposed), row.proposed.ifBlank { "—" })
    }
}

private fun homeAmount(amount: Long?, expense: com.ticketbox.domain.model.Expense): String =
    formatDisplayAmount(amount, CurrencyDisplay.forRecord(expense.homeCurrencyCode ?: expense.homeCurrency.storageKey))

@Composable
private fun CollectionReviewChoice(title: String, current: String, original: String, keep: Boolean?, choose: (Boolean) -> Unit) {
    Column {
        Text(title, style = MaterialTheme.typography.titleSmall)
        AppValueComparison(stringResource(R.string.expense_correction_comparison_current), current.ifBlank { "—" },
            stringResource(R.string.expense_correction_comparison_proposed), original.ifBlank { "—" })
        ReviewChoice(keep, choose)
    }
}

@Composable
private fun ReviewChoice(keep: Boolean?, choose: (Boolean) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        listOf(false, true).forEach { selected ->
            Row(Modifier.fillMaxWidth().selectable(keep == selected, role = Role.RadioButton, onClick = { choose(selected) })
                .padding(vertical = AppSpacing.smallGap), verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
                RadioButton(selected = keep == selected, onClick = null)
                Text(stringResource(if (selected) R.string.expense_correction_review_keep_rows else R.string.expense_correction_review_use_current))
            }
        }
    }
}
