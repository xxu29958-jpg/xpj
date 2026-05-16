package com.ticketbox.ui.screens.ledger

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.screens.SelectableFilterChip
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.LedgerUiState

@Composable
internal fun LedgerFilterPanel(
    state: LedgerUiState,
    onOpenMonthPicker: () -> Unit,
    onOpenTools: () -> Unit,
    onManualAdd: () -> Unit,
    onCategoryChange: (String) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.compactPadding)) {
        LedgerHeader(state = state, onManualAdd = onManualAdd)
        LedgerInlineFilters(
            state = state,
            onOpenMonthPicker = onOpenMonthPicker,
            onOpenTools = onOpenTools,
            onCategoryChange = onCategoryChange,
        )
        Text(
            text = ledgerCombinedStatusLine(state),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
            fontWeight = FontWeight.Medium,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun LedgerInlineFilters(
    state: LedgerUiState,
    onOpenMonthPicker: () -> Unit,
    onOpenTools: () -> Unit,
    onCategoryChange: (String) -> Unit,
) {
    val hasQuery = state.query.isNotBlank()
    val hasTag = state.tagFilter.isNotBlank()
    val quickCategories = remember(state.categories) { state.categories.take(2) }
    val selectedOutsideQuick = state.categoryFilter.isNotBlank() && state.categoryFilter !in quickCategories
    LazyRow(horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap)) {
        item {
            AppFilterChip(
                selected = true,
                onClick = onOpenMonthPicker,
                label = displayMonthLabel(state.monthFilter).takeIf { state.monthFilter.isNotBlank() } ?: "全部月份",
                trailingIcon = {
                    Icon(
                        imageVector = Icons.Filled.ExpandMore,
                        contentDescription = "选择月份",
                        modifier = Modifier.size(FilterChipDefaults.IconSize),
                    )
                },
            )
        }
        item {
            SelectableFilterChip(
                selected = state.categoryFilter.isBlank(),
                label = "全部分类",
                onClick = { onCategoryChange("") },
            )
        }
        items(quickCategories, key = { it }) { category ->
            SelectableFilterChip(
                selected = state.categoryFilter == category,
                label = category,
                onClick = { onCategoryChange(category) },
            )
        }
        item {
            AppFilterChip(
                selected = hasQuery,
                onClick = onOpenTools,
                label = if (hasQuery) "已搜索" else "搜索备注",
                leadingIcon = if (hasQuery) {
                    {
                        Icon(
                            imageVector = Icons.Filled.Check,
                            contentDescription = null,
                            modifier = Modifier.size(FilterChipDefaults.IconSize),
                        )
                    }
                } else {
                    null
                },
            )
        }
        if (hasTag) {
            item {
                AppFilterChip(
                    selected = true,
                    onClick = onOpenTools,
                    label = "#${state.tagFilter}",
                    leadingIcon = {
                        Icon(
                            imageVector = Icons.Filled.Check,
                            contentDescription = null,
                            modifier = Modifier.size(FilterChipDefaults.IconSize),
                        )
                    },
                )
            }
        }
        item {
            AppFilterChip(
                selected = selectedOutsideQuick,
                onClick = onOpenTools,
                label = if (selectedOutsideQuick) state.categoryFilter else "更多",
            )
        }
    }
}

@Composable
internal fun LedgerInlineButton(
    text: String,
    modifier: Modifier,
    enabled: Boolean,
    onClick: () -> Unit,
) {
    OutlinedButton(
        modifier = modifier.heightIn(min = AppSpacing.controlMinHeight),
        enabled = enabled,
        onClick = onClick,
        contentPadding = PaddingValues(horizontal = AppSpacing.compactPadding, vertical = 0.dp),
    ) {
        Text(
            text = text,
            maxLines = 1,
            softWrap = false,
            overflow = TextOverflow.Ellipsis,
        )
    }
}
