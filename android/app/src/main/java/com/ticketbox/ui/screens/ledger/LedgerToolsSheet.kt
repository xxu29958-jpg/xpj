package com.ticketbox.ui.screens.ledger

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.CallSplit
import androidx.compose.material.icons.automirrored.filled.ReceiptLong
import androidx.compose.material.icons.filled.AccountBalanceWallet
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.FileDownload
import androidx.compose.material.icons.filled.Payments
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.ui.components.AppSegmentedControl
import com.ticketbox.ui.components.AppSegmentedItem
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.viewmodel.LedgerUiState
import com.ticketbox.viewmodel.LedgerViewMode

@Composable
internal fun LedgerToolsSheet(
    state: LedgerUiState,
    canExport: Boolean,
    onCategoryChange: (String) -> Unit,
    onTagChange: (String) -> Unit,
    onQueryChange: (String) -> Unit,
    onClearFilters: () -> Unit,
    onViewModeChange: (LedgerViewMode) -> Unit,
    onSync: () -> Unit,
    onExportCsv: () -> Unit,
    onOpenBillSplit: () -> Unit,
    onOpenDebts: () -> Unit,
    onOpenReceivables: () -> Unit,
    onOpenRepaymentDrafts: () -> Unit,
    onOpenGlobalSearch: () -> Unit,
    onDismiss: () -> Unit,
) {
    val hasUserFilters = state.categoryFilter.isNotBlank() || state.tagFilter.isNotBlank() || state.query.isNotBlank()
    AppSheetScaffold(
        title = stringResource(R.string.ledger_tools_title),
        subtitle = stringResource(R.string.ledger_tools_subtitle),
    ) {
        LedgerFilterTools(
            state = state,
            onCategoryChange = onCategoryChange,
            onTagChange = onTagChange,
            onQueryChange = onQueryChange,
            onOpenGlobalSearch = onOpenGlobalSearch,
        )
        LedgerToolDivider()
        LedgerViewTools(
            selectedMode = state.viewMode,
            onViewModeChange = onViewModeChange,
        )
        LedgerToolDivider()
        LedgerDataTools(
            state = state,
            canExport = canExport,
            onSync = onSync,
            onExportCsv = onExportCsv,
        )
        LedgerToolDivider()
        LedgerRelationshipTools(
            onOpenBillSplit = onOpenBillSplit,
            onOpenDebts = onOpenDebts,
            onOpenReceivables = onOpenReceivables,
            onOpenRepaymentDrafts = onOpenRepaymentDrafts,
        )
        LedgerToolsFooter(
            hasUserFilters = hasUserFilters,
            showNoExport = state.items.isEmpty(),
            onClearFilters = onClearFilters,
            onDismiss = onDismiss,
        )
    }
}

@Composable
private fun LedgerViewTools(
    selectedMode: LedgerViewMode,
    onViewModeChange: (LedgerViewMode) -> Unit,
) {
    val cardLabel = stringResource(R.string.ledger_view_mode_card)
    val listLabel = stringResource(R.string.ledger_view_mode_list)
    val tableLabel = stringResource(R.string.ledger_view_mode_table)
    LedgerToolSection(title = stringResource(R.string.ledger_tools_view_title)) {
        AppSegmentedControl(
            options = LedgerViewMode.entries.map { mode ->
                AppSegmentedItem(
                    value = mode,
                    label = when (mode) {
                        LedgerViewMode.Card -> cardLabel
                        LedgerViewMode.List -> listLabel
                        LedgerViewMode.Table -> tableLabel
                    },
                )
            },
            selectedValue = selectedMode,
            onValueChange = onViewModeChange,
        )
    }
}

@Composable
private fun LedgerToolSection(
    title: String,
    content: @Composable () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        Text(
            text = title,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelLarge,
            fontWeight = AppTextHierarchy.heading.weight,
        )
        content()
    }
}

@Composable
private fun LedgerToolDivider() {
    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.24f))
}

@Composable
private fun LedgerFilterTools(
    state: LedgerUiState,
    onCategoryChange: (String) -> Unit,
    onTagChange: (String) -> Unit,
    onQueryChange: (String) -> Unit,
    onOpenGlobalSearch: () -> Unit,
) {
    LedgerToolSection(title = stringResource(R.string.ledger_tools_filter_title)) {
        AppTextInput(
            state = AppTextInputState(
                label = stringResource(R.string.ledger_tools_search_label),
                value = state.query,
                placeholder = stringResource(R.string.ledger_tools_search_placeholder),
            ),
            actions = AppTextInputActions(onValueChange = onQueryChange),
            modifier = Modifier.fillMaxWidth(),
        )
        LedgerInlineButton(
            text = stringResource(R.string.ledger_tools_global_search),
            modifier = Modifier.fillMaxWidth(),
            enabled = true,
            onClick = onOpenGlobalSearch,
            icon = Icons.Default.Search,
        )
        val categoryOptions = if (state.categoryFilter.isNotBlank() && state.categoryFilter !in state.categories) {
            listOf(state.categoryFilter) + state.categories
        } else {
            state.categories
        }
        LedgerOptionList(
            state = LedgerOptionListState(
                title = stringResource(R.string.ledger_category_filter_label),
                allLabel = stringResource(R.string.ledger_category_filter_all),
                options = categoryOptions,
                selectedValue = state.categoryFilter,
            ),
            onValueChange = onCategoryChange,
        )
        if (state.tags.isNotEmpty() || state.tagFilter.isNotBlank()) {
            val tagOptions = if (state.tagFilter.isNotBlank() && state.tagFilter !in state.tags) {
                listOf(state.tagFilter) + state.tags
            } else {
                state.tags
            }
            LedgerOptionList(
                state = LedgerOptionListState(
                    title = stringResource(R.string.ledger_tools_tag_label),
                    allLabel = stringResource(R.string.ledger_tools_tag_all),
                    options = tagOptions,
                    selectedValue = state.tagFilter,
                    labelPrefix = "#",
                ),
                onValueChange = onTagChange,
            )
        }
    }
}

@Composable
private fun LedgerDataTools(
    state: LedgerUiState,
    canExport: Boolean,
    onSync: () -> Unit,
    onExportCsv: () -> Unit,
) {
    LedgerToolSection(title = stringResource(R.string.ledger_tools_actions_title)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        ) {
            LedgerInlineButton(
                text = if (state.exporting) {
                    stringResource(R.string.ledger_tools_exporting)
                } else {
                    stringResource(R.string.ledger_tools_export)
                },
                modifier = Modifier.weight(1f),
                enabled = canExport,
                onClick = onExportCsv,
                icon = Icons.Default.FileDownload,
            )
            LedgerInlineButton(
                text = if (state.syncing) {
                    stringResource(R.string.ledger_tools_syncing)
                } else {
                    stringResource(R.string.ledger_tools_update_ledger)
                },
                modifier = Modifier.weight(1f),
                enabled = !state.syncing,
                onClick = onSync,
                icon = Icons.Default.Sync,
            )
        }
    }
}

@Composable
private fun LedgerToolsFooter(
    hasUserFilters: Boolean,
    showNoExport: Boolean,
    onClearFilters: () -> Unit,
    onDismiss: () -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        ) {
            if (hasUserFilters) {
                QuietOutlinedButton(
                    text = stringResource(R.string.ledger_tools_clear_filters),
                    modifier = Modifier.weight(1f),
                    onClick = onClearFilters,
                )
            }
            Button(
                modifier = if (hasUserFilters) Modifier.weight(1f) else Modifier.fillMaxWidth(),
                onClick = onDismiss,
            ) {
                Text(stringResource(R.string.ledger_tools_done))
            }
        }
        if (showNoExport) {
            Text(
                text = stringResource(R.string.ledger_tools_no_export),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

@Composable
private fun LedgerRelationshipTools(
    onOpenBillSplit: () -> Unit,
    onOpenDebts: () -> Unit,
    onOpenReceivables: () -> Unit,
    onOpenRepaymentDrafts: () -> Unit,
) {
    LedgerToolSection(title = stringResource(R.string.ledger_tools_relationship_title)) {
        LedgerInlineButton(
            text = stringResource(R.string.ledger_tools_bill_split),
            modifier = Modifier.fillMaxWidth(),
            enabled = true,
            onClick = onOpenBillSplit,
            icon = Icons.AutoMirrored.Filled.CallSplit,
        )
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        ) {
            LedgerInlineButton(
                text = stringResource(R.string.ledger_tools_debts),
                modifier = Modifier.weight(1f),
                enabled = true,
                onClick = onOpenDebts,
                icon = Icons.Default.AccountBalanceWallet,
            )
            LedgerInlineButton(
                text = stringResource(R.string.ledger_tools_receivables),
                modifier = Modifier.weight(1f),
                enabled = true,
                onClick = onOpenReceivables,
                icon = Icons.Default.Payments,
            )
        }
        LedgerInlineButton(
            text = stringResource(R.string.ledger_tools_repayment_drafts),
            modifier = Modifier.fillMaxWidth(),
            enabled = true,
            onClick = onOpenRepaymentDrafts,
            icon = Icons.AutoMirrored.Filled.ReceiptLong,
        )
    }
}

@Immutable
private data class LedgerOptionListState(
    val title: String,
    val allLabel: String,
    val options: List<String>,
    val selectedValue: String,
    val labelPrefix: String = "",
)

@Composable
private fun LedgerOptionList(
    state: LedgerOptionListState,
    onValueChange: (String) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
        Text(
            text = state.title,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelMedium,
        )
        Column(modifier = Modifier.fillMaxWidth()) {
            LedgerOptionRow(
                label = state.allLabel,
                selected = state.selectedValue.isBlank(),
                onClick = { onValueChange("") },
            )
            state.options.forEach { option ->
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.subtle))
                LedgerOptionRow(
                    label = "${state.labelPrefix}$option",
                    selected = state.selectedValue == option,
                    onClick = { onValueChange(option) },
                )
            }
        }
    }
}

@Composable
private fun LedgerOptionRow(
    label: String,
    selected: Boolean,
    onClick: () -> Unit,
) {
    val visuals = LocalThemeVisuals.current
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = AppSpacing.controlMinHeight)
            .clip(RoundedCornerShape(AppRadius.extraSmall))
            .then(
                if (selected) {
                    Modifier.background(visuals.chipSelected.copy(alpha = AppAlpha.soft))
                } else {
                    Modifier
                },
            )
            .selectable(selected = selected, role = Role.RadioButton, onClick = onClick)
            .padding(horizontal = AppSpacing.compactPadding, vertical = AppSpacing.smallGap),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = label,
            modifier = Modifier.weight(1f),
            color = if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.bodyMedium,
            fontWeight = if (selected) AppTextHierarchy.heading.weight else AppTextHierarchy.body.weight,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        if (selected) {
            Icon(
                imageVector = Icons.Filled.Check,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(18.dp),
            )
        }
    }
}
