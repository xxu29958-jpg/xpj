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
import androidx.compose.material3.Switch
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
import com.ticketbox.ui.components.AppAdaptiveContentActionStateRow
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSheetAction
import com.ticketbox.ui.components.AppSheetActionRow
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.components.QuietOutlinedButton
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
            verticalAlignment = Alignment.CenterVertically,
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
        QuietOutlinedButton(
            text = stringResource(R.string.ledger_selection_select_all),
            enabled = !state.applying,
            modifier = buttonModifier,
            onClick = actions.onSelectAll,
        )
        AppPrimaryButton(
            text = stringResource(R.string.ledger_selection_edit),
            icon = Icons.Filled.Edit,
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
@Composable
internal fun LedgerBulkEditSheet(
    selectedCount: Int,
    selectedHaveTags: Boolean,
    categories: List<String>,
    applying: Boolean,
    onApplyCategory: (String) -> Unit,
    onApplyTags: (String) -> Unit,
) {
    var category by rememberSaveable { mutableStateOf("") }
    var tagsEnabled by rememberSaveable { mutableStateOf(false) }
    var tags by rememberSaveable { mutableStateOf("") }
    var showTagConfirm by remember { mutableStateOf(false) }

    AppSheetScaffold(title = stringResource(R.string.ledger_bulk_title, selectedCount)) {
        LedgerBulkCategorySection(
            state = LedgerBulkCategoryState(
                category = category,
                categories = categories,
                applying = applying,
                selectedCount = selectedCount,
            ),
            actions = LedgerBulkCategoryActions(
                onCategoryChange = { category = it },
                onApplyCategory = { onApplyCategory(category) },
            ),
        )
        LedgerBulkTagsSection(
            state = LedgerBulkTagsState(
                tagsEnabled = tagsEnabled,
                tags = tags,
                applying = applying,
                selectedCount = selectedCount,
            ),
            actions = LedgerBulkTagsActions(
                onTagsEnabledChange = { tagsEnabled = it },
                onTagsChange = { tags = it },
                onApplyTags = {
                    if (selectedHaveTags) {
                        showTagConfirm = true
                    } else {
                        onApplyTags(tags)
                    }
                },
            ),
        )
    }

    if (showTagConfirm) {
        AlertDialog(
            onDismissRequest = { showTagConfirm = false },
            title = { Text(stringResource(R.string.ledger_bulk_tags_confirm_title)) },
            text = { Text(stringResource(R.string.ledger_bulk_tags_confirm_message)) },
            confirmButton = {
                TextButton(onClick = {
                    showTagConfirm = false
                    onApplyTags(tags)
                }) { Text(stringResource(R.string.ledger_bulk_tags_confirm_replace)) }
            },
            dismissButton = {
                TextButton(onClick = { showTagConfirm = false }) { Text(stringResource(R.string.common_cancel)) }
            },
        )
    }
}

@Immutable
private data class LedgerBulkCategoryState(
    val category: String,
    val categories: List<String>,
    val applying: Boolean,
    val selectedCount: Int,
)

private data class LedgerBulkCategoryActions(
    val onCategoryChange: (String) -> Unit,
    val onApplyCategory: () -> Unit,
)

@Composable
private fun LedgerBulkCategorySection(
    state: LedgerBulkCategoryState,
    actions: LedgerBulkCategoryActions,
) {
    ExpenseEditCategoryField(
        category = state.category,
        categories = state.categories,
        onCategoryChange = actions.onCategoryChange,
        enabled = !state.applying,
    )
    AppSheetActionRow(
        primary = AppSheetAction(
            text = stringResource(R.string.ledger_bulk_apply_category, state.selectedCount),
            enabled = state.category.isNotBlank() && !state.applying,
            onClick = actions.onApplyCategory,
        ),
    )
}

@Immutable
private data class LedgerBulkTagsState(
    val tagsEnabled: Boolean,
    val tags: String,
    val applying: Boolean,
    val selectedCount: Int,
)

private data class LedgerBulkTagsActions(
    val onTagsEnabledChange: (Boolean) -> Unit,
    val onTagsChange: (String) -> Unit,
    val onApplyTags: () -> Unit,
)

@Composable
private fun LedgerBulkTagsSection(
    state: LedgerBulkTagsState,
    actions: LedgerBulkTagsActions,
) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(
            text = stringResource(R.string.ledger_bulk_replace_tags_title),
            style = MaterialTheme.typography.titleSmall,
            modifier = Modifier.weight(1f),
        )
        Switch(
            checked = state.tagsEnabled,
            onCheckedChange = actions.onTagsEnabledChange,
            enabled = !state.applying,
        )
    }
    if (!state.tagsEnabled) return
    AppTextInput(
        state = AppTextInputState(
            label = stringResource(R.string.ledger_bulk_tags_label),
            value = state.tags,
            placeholder = stringResource(R.string.ledger_bulk_tags_placeholder),
            enabled = !state.applying,
        ),
        actions = AppTextInputActions(onValueChange = actions.onTagsChange),
        modifier = Modifier.fillMaxWidth(),
    )
    Text(
        text = stringResource(R.string.ledger_bulk_tags_replace_warning),
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.error,
    )
    AppSheetActionRow(
        primary = AppSheetAction(
            text = stringResource(R.string.ledger_bulk_apply_tags, state.selectedCount),
            enabled = state.tags.isNotBlank() && !state.applying,
            onClick = actions.onApplyTags,
        ),
    )
}
