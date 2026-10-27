package com.ticketbox.ui.screens.ledger

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppEndAlignedAmountText
import com.ticketbox.ui.components.AppAdaptiveAmountRowDefaults
import com.ticketbox.ui.components.AppAdaptiveContentActionStyle
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.components.AppListRow
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.presentation.formatExpensePrimaryAmount
import com.ticketbox.ui.components.expenseTimeLabel
import com.ticketbox.ui.components.AppAdaptiveContentActionStateRow
import com.ticketbox.ui.components.AppButtonIcons
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSheetAction
import com.ticketbox.ui.components.AppSheetActionRow
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.expense.ExpenseEditCategoryField

/**
 * ADR-0042 Slice C: in-content contextual action bar shown while the ledger is
 * in multi-select mode. The ledger has no TopAppBar to transform, so this bar
 * carries the exit, selection count, select-all, and edit affordances in place.
 */
@Composable
internal fun LedgerSelectionBar(
    selectedCount: Int,
    applying: Boolean,
    onExit: () -> Unit,
    onSelectAll: () -> Unit,
    onEdit: () -> Unit,
) {
    Column(modifier = Modifier.fillMaxWidth()) {
        AppAdaptiveContentActionStateRow(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = AppSpacing.cardPaddingTight, vertical = AppSpacing.smallGap),
            content = {
                LedgerSelectionSummary(
                    selectedCount = selectedCount,
                    applying = applying,
                    onExit = onExit,
                    modifier = Modifier.fillMaxWidth(),
                )
            },
        ) { actionModifier, stacked ->
            LedgerSelectionActions(
                modifier = actionModifier,
                stacked = stacked,
                state = LedgerSelectionActionState(selectedCount = selectedCount, applying = applying),
                actions = LedgerSelectionActionCallbacks(onSelectAll = onSelectAll, onEdit = onEdit),
            )
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.24f))
    }
}

@Composable
private fun LedgerSelectionSummary(
    selectedCount: Int,
    applying: Boolean,
    onExit: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier,
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        IconButton(onClick = onExit, enabled = !applying) {
            Icon(Icons.Filled.Close, contentDescription = stringResource(R.string.ledger_selection_exit_description))
        }
        Text(
            text = stringResource(R.string.ledger_selection_count, selectedCount),
            style = MaterialTheme.typography.titleSmall,
            modifier = Modifier.weight(1f),
        )
    }
}

@Immutable
private data class LedgerSelectionActionState(
    val selectedCount: Int,
    val applying: Boolean,
)

private data class LedgerSelectionActionCallbacks(
    val onSelectAll: () -> Unit,
    val onEdit: () -> Unit,
)

@Composable
private fun LedgerSelectionActions(
    modifier: Modifier,
    stacked: Boolean,
    state: LedgerSelectionActionState,
    actions: LedgerSelectionActionCallbacks,
) {
    Row(
        modifier = modifier,
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        val buttonModifier = if (stacked) Modifier.weight(1f) else Modifier
        AppSecondaryButton(
            text = stringResource(R.string.ledger_selection_select_all),
            enabled = !state.applying,
            modifier = buttonModifier,
            onClick = actions.onSelectAll,
        )
        AppPrimaryButton(
            text = stringResource(R.string.ledger_selection_edit),
            icons = AppButtonIcons(leading = Icons.Filled.Edit),
            enabled = state.selectedCount > 0 && !state.applying,
            modifier = buttonModifier,
            onClick = actions.onEdit,
        )
    }
}

/**
 * ADR-0042 Slice C: bulk-edit sheet for the selected confirmed expenses.
 * Category is the primary action; tags are opt-in because the client sends the
 * whole tag string, so applying tags replaces existing tags instead of merging.
 */
@Immutable
internal data class LedgerBulkEditSheetState(
    val selectedCount: Int,
    val selectedHaveTags: Boolean,
    val categories: List<String>,
    val applying: Boolean,
    val selectedExpenses: List<Expense>,
    val canModify: Boolean = true,
    val message: UiText? = null,
) {
    val editable: Boolean get() = canModify && !applying
    val selectionAvailable: Boolean get() = selectedCount > 0 && selectedExpenses.size == selectedCount
    fun canApply(value: String, reason: String): Boolean =
        editable && selectionAvailable && value.isNotBlank() && reason.isNotBlank()
}

internal data class LedgerBulkEditSheetActions(
    val onApplyCategory: (category: String, reason: String) -> Unit,
    val onApplyTags: (tags: String, reason: String) -> Unit,
    val onDismiss: () -> Unit,
)

@Composable
internal fun LedgerBulkEditSheet(
    state: LedgerBulkEditSheetState,
    actions: LedgerBulkEditSheetActions,
) {
    var category by rememberSaveable { mutableStateOf("") }
    var tagsEnabled by rememberSaveable { mutableStateOf(false) }
    var tags by rememberSaveable { mutableStateOf("") }
    var reason by rememberSaveable { mutableStateOf("") }
    var showTagConfirm by remember { mutableStateOf(false) }
    val editable = state.editable
    val completeSelection = state.selectionAvailable
    val value = if (tagsEnabled) tags else category

    AppSheetScaffold(
        title = stringResource(R.string.ledger_bulk_title, state.selectedCount),
        subtitle = stringResource(R.string.ledger_bulk_preview_subtitle),
        actions = {
            AppSheetActionRow(primary = AppSheetAction(
                text = stringResource(if (tagsEnabled) R.string.ledger_bulk_apply_tags
                    else R.string.ledger_bulk_apply_category, state.selectedCount),
                enabled = state.canApply(value, reason),
                onClick = {
                    if (!tagsEnabled) actions.onApplyCategory(category, reason.trim())
                    else if (state.selectedHaveTags) showTagConfirm = true
                    else actions.onApplyTags(tags, reason.trim())
                },
            ))
            TextButton(onClick = actions.onDismiss, enabled = !state.applying,
                modifier = Modifier.fillMaxWidth()) {
                Text(stringResource(R.string.ledger_bulk_keep_selection))
            }
        },
    ) {
        if (!state.canModify) AppStatusBanner(
            message = UiText.res(R.string.common_readonly_ledger), tone = MessageTone.Info,
        )
        state.message?.let { AppStatusBanner(message = it, tone = MessageTone.Danger) }
        if (!completeSelection) AppStatusBanner(
            message = UiText.res(R.string.ledger_bulk_selection_unavailable), tone = MessageTone.Danger,
        )
        LedgerBulkSelectionPreview(state.selectedExpenses, tagsEnabled, value)
        if (!tagsEnabled) ExpenseEditCategoryField(
            category = category, categories = state.categories,
            onCategoryChange = { category = it }, enabled = editable,
        ) else LedgerBulkTagsSection(tags = tags, enabled = editable, onTagsChange = { tags = it })
        AppTextInput(
            state = AppTextInputState(
                label = stringResource(R.string.ledger_bulk_reason_label), value = reason,
                placeholder = stringResource(R.string.ledger_bulk_reason_placeholder), enabled = editable,
            ),
            actions = AppTextInputActions(onValueChange = { reason = it }),
            modifier = Modifier.fillMaxWidth(),
        )
        Text(stringResource(R.string.ledger_bulk_unchanged), style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
        TextButton(onClick = { tagsEnabled = !tagsEnabled }, enabled = editable) {
            Text(stringResource(if (tagsEnabled) R.string.ledger_bulk_replace_category_title
                else R.string.ledger_bulk_replace_tags_title))
        }
    }

    if (showTagConfirm) {
        AlertDialog(
            onDismissRequest = { showTagConfirm = false },
            title = { Text(stringResource(R.string.ledger_bulk_tags_confirm_title)) },
            text = { Text(stringResource(R.string.ledger_bulk_tags_confirm_message)) },
            confirmButton = {
                TextButton(enabled = editable && completeSelection, onClick = {
                    showTagConfirm = false
                    actions.onApplyTags(tags, reason.trim())
                }) { Text(stringResource(R.string.ledger_bulk_tags_confirm_replace)) }
            },
            dismissButton = {
                TextButton(onClick = { showTagConfirm = false }) { Text(stringResource(R.string.common_cancel)) }
            },
        )
    }
}

@Composable
private fun LedgerBulkSelectionPreview(expenses: List<Expense>, tagsEnabled: Boolean, value: String) {
    var showAll by rememberSaveable { mutableStateOf(false) }
    val visible = if (showAll) expenses else expenses.take(LedgerBulkPreviewLimit)
    Column {
        visible.forEach { expense ->
            AppListRow {
                AppAdaptiveContentActionStateRow(
                    style = AppAdaptiveContentActionStyle(
                        wideActionWeight = AppAdaptiveAmountRowDefaults.trailingWeight, amountTrailing = true,
                    ),
                    content = {
                        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
                            Text(expense.merchant?.takeIf { it.isNotBlank() }
                                ?: stringResource(R.string.ledger_item_merchant_empty), style = MaterialTheme.typography.titleSmall)
                            Text(expenseTimeLabel(expense).asString(), style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant)
                            val original = (if (tagsEnabled) expense.tags else expense.category).orEmpty().ifBlank {
                                stringResource(R.string.ledger_bulk_value_empty)
                            }
                            Text(
                                text = if (value.isBlank()) original
                                    else stringResource(R.string.ledger_bulk_value_change, original, value),
                                style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.primary,
                            )
                        }
                    },
                    action = { amountModifier, _ ->
                        AppEndAlignedAmountText(text = formatExpensePrimaryAmount(expense),
                            modifier = amountModifier, role = AppAmountRole.Compact)
                    },
                )
            }
        }
        if (expenses.size > LedgerBulkPreviewLimit) TextButton(onClick = { showAll = !showAll }) {
            Text(if (showAll) stringResource(R.string.ledger_bulk_preview_less)
                else stringResource(R.string.ledger_bulk_preview_all, expenses.size))
        }
    }
}

private const val LedgerBulkPreviewLimit = 3

@Composable
private fun LedgerBulkTagsSection(
    tags: String,
    enabled: Boolean,
    onTagsChange: (String) -> Unit,
) {
    AppTextInput(
        state = AppTextInputState(
            label = stringResource(R.string.ledger_bulk_tags_label),
            value = tags,
            placeholder = stringResource(R.string.ledger_bulk_tags_placeholder),
            enabled = enabled,
        ),
        actions = AppTextInputActions(onValueChange = onTagsChange),
        modifier = Modifier.fillMaxWidth(),
    )
    Text(
        text = stringResource(R.string.ledger_bulk_tags_replace_warning),
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.error,
    )
}
