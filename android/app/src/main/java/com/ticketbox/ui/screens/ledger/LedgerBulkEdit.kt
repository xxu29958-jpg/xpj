package com.ticketbox.ui.screens.ledger

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
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
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSheetAction
import com.ticketbox.ui.components.AppSheetActionRow
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.design.AppAdaptiveBreakpoints
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
        BoxWithConstraints(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = AppSpacing.cardPaddingTight, vertical = AppSpacing.smallGap),
        ) {
            val shouldStackActions = maxWidth < AppAdaptiveBreakpoints.contentActionInlineMinWidth
            if (shouldStackActions) {
                Column(
                    modifier = Modifier.fillMaxWidth(),
                    verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
                ) {
                    LedgerSelectionSummary(selectedCount = selectedCount, applying = applying, onExit = onExit)
                    LedgerSelectionActions(
                        expanded = true,
                        selectedCount = selectedCount,
                        applying = applying,
                        onSelectAll = onSelectAll,
                        onEdit = onEdit,
                    )
                }
            } else {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    LedgerSelectionSummary(
                        selectedCount = selectedCount,
                        applying = applying,
                        onExit = onExit,
                        modifier = Modifier.weight(1f),
                    )
                    LedgerSelectionActions(
                        expanded = false,
                        selectedCount = selectedCount,
                        applying = applying,
                        onSelectAll = onSelectAll,
                        onEdit = onEdit,
                    )
                }
            }
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

@Composable
private fun LedgerSelectionActions(
    expanded: Boolean,
    selectedCount: Int,
    applying: Boolean,
    onSelectAll: () -> Unit,
    onEdit: () -> Unit,
) {
    Row(
        modifier = if (expanded) Modifier.fillMaxWidth() else Modifier,
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        val buttonModifier = if (expanded) Modifier.weight(1f) else Modifier.widthIn(min = 88.dp)
        QuietOutlinedButton(
            text = stringResource(R.string.ledger_selection_select_all),
            enabled = !applying,
            modifier = buttonModifier,
            onClick = onSelectAll,
        )
        AppPrimaryButton(
            text = stringResource(R.string.ledger_selection_edit),
            icon = Icons.Filled.Edit,
            enabled = selectedCount > 0 && !applying,
            modifier = buttonModifier,
            onClick = onEdit,
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
