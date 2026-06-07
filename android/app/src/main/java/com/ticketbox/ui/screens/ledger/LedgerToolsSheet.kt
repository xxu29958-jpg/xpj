package com.ticketbox.ui.screens.ledger

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
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
    onDismiss: () -> Unit,
) {
    val hasUserFilters = state.categoryFilter.isNotBlank() || state.tagFilter.isNotBlank() || state.query.isNotBlank()
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = AppSpacing.cardPaddingSmall, vertical = AppSpacing.compactGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.cardPaddingTight),
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
            Text(stringResource(R.string.ledger_tools_title), style = MaterialTheme.typography.titleLarge, fontWeight = AppTextHierarchy.heading.weight)
            Text(
                text = ledgerCombinedStatusLine(state),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
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
                .height(52.dp),
            placeholder = { Text(stringResource(R.string.ledger_tools_search_placeholder)) },
            singleLine = true,
        )
        Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
            LedgerInlineButton(
                text = if (state.exporting) {
                    stringResource(R.string.ledger_tools_exporting)
                } else {
                    stringResource(R.string.ledger_tools_export)
                },
                modifier = Modifier.weight(1f),
                enabled = canExport,
                onClick = onExportCsv,
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
            )
        }
        Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
            if (hasUserFilters) {
                QuietOutlinedButton(
                    text = stringResource(R.string.ledger_tools_clear_filters),
                    modifier = Modifier.weight(1f),
                    onClick = onClearFilters,
                )
            }
            Button(
                modifier = Modifier.weight(1f),
                onClick = onDismiss,
            ) {
                Text(stringResource(R.string.ledger_tools_done))
            }
        }
        if (state.items.isEmpty()) {
            Text(
                text = stringResource(R.string.ledger_tools_no_export),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
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
