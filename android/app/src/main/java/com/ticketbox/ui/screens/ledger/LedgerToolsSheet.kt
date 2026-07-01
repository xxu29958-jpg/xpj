package com.ticketbox.ui.screens.ledger

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.CallSplit
import androidx.compose.material.icons.automirrored.filled.ReceiptLong
import androidx.compose.material.icons.filled.AccountBalanceWallet
import androidx.compose.material.icons.filled.FileDownload
import androidx.compose.material.icons.filled.Payments
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.R
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.screens.CategoryFilterRow
import com.ticketbox.ui.screens.SelectableFilterChip
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.viewmodel.LedgerUiState

@Composable
internal fun LedgerToolsSheet(
    state: LedgerUiState,
    canExport: Boolean,
    onCategoryChange: (String) -> Unit,
    onTagChange: (String) -> Unit,
    onQueryChange: (String) -> Unit,
    onClearFilters: () -> Unit,
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
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = AppSpacing.cardPaddingSmall, vertical = AppSpacing.compactGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        LedgerToolsHeader(state = state)
        LedgerToolDivider()
        LedgerRelationshipTools(
            onOpenBillSplit = onOpenBillSplit,
            onOpenDebts = onOpenDebts,
            onOpenReceivables = onOpenReceivables,
            onOpenRepaymentDrafts = onOpenRepaymentDrafts,
        )
        LedgerToolDivider()
        LedgerFilterTools(
            state = state,
            onCategoryChange = onCategoryChange,
            onTagChange = onTagChange,
            onQueryChange = onQueryChange,
            onOpenGlobalSearch = onOpenGlobalSearch,
        )
        LedgerToolDivider()
        LedgerDataTools(
            state = state,
            canExport = canExport,
            onSync = onSync,
            onExportCsv = onExportCsv,
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
private fun LedgerToolsHeader(state: LedgerUiState) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
        Text(
            text = stringResource(R.string.ledger_tools_title),
            style = MaterialTheme.typography.titleLarge,
            fontWeight = AppTextHierarchy.heading.weight,
        )
        Text(
            text = ledgerCombinedStatusLine(state),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
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
        CategoryFilterRow(
            categories = state.categories,
            selectedCategory = state.categoryFilter,
            onCategoryChange = onCategoryChange,
        )
        if (state.tags.isNotEmpty() || state.tagFilter.isNotBlank()) {
            TagFilterRow(
                tags = state.tags,
                selectedTag = state.tagFilter,
                onTagChange = onTagChange,
            )
        }
        OutlinedTextField(
            value = state.query,
            onValueChange = onQueryChange,
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(min = AppSpacing.controlMinHeight + AppSpacing.compactGap),
            placeholder = { Text(stringResource(R.string.ledger_tools_search_placeholder)) },
            singleLine = true,
        )
        LedgerInlineButton(
            text = stringResource(R.string.ledger_tools_global_search),
            modifier = Modifier.fillMaxWidth(),
            enabled = true,
            onClick = onOpenGlobalSearch,
            icon = Icons.Default.Search,
        )
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

@Composable
private fun TagFilterRow(
    tags: List<String>,
    selectedTag: String,
    onTagChange: (String) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
        Text(
            text = stringResource(R.string.ledger_tools_tag_label),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelMedium,
        )
        LazyRow(horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            item {
                SelectableFilterChip(
                    selected = selectedTag.isBlank(),
                    label = stringResource(R.string.ledger_tools_tag_all),
                    onClick = { onTagChange("") },
                )
            }
            items(tags, key = { it }) { tag ->
                SelectableFilterChip(
                    selected = selectedTag == tag,
                    label = "#$tag",
                    onClick = { onTagChange(tag) },
                )
            }
        }
    }
}
