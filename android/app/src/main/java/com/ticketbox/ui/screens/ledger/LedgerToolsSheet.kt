package com.ticketbox.ui.screens.ledger

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Category
import androidx.compose.material.icons.filled.FileDownload
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.components.AppAdaptiveEqualControlRow
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.ui.components.AppSegmentedControl
import com.ticketbox.ui.components.AppSegmentedItem
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.components.buildAppTagFilterChoices
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.viewmodel.LedgerUiState
import com.ticketbox.viewmodel.LedgerViewMode

@Immutable
internal data class LedgerToolsSheetState(
    val ledger: LedgerUiState,
    val canExport: Boolean,
)

// The data-quality drill counts as a user-visible filter here too: without it
// the footer hid 清除筛选 for a DQ-only view while the export note in the same
// sheet tells the user to clear the filter first.
internal fun ledgerHasUserVisibleFilters(state: LedgerUiState): Boolean =
    state.categoryFilter.isNotBlank() ||
        state.tagFilter.isNotBlank() ||
        state.query.isNotBlank() ||
        state.dataQualityFilter != null

@Immutable
internal data class LedgerToolsSheetActions(
    val onCategoryChange: (String) -> Unit,
    val onTagChange: (String) -> Unit,
    val onQueryChange: (String) -> Unit,
    val onClearFilters: () -> Unit,
    val onViewModeChange: (LedgerViewMode) -> Unit,
    val onSync: () -> Unit,
    val onExportCsv: () -> Unit,
    val onOpenLibrary: () -> Unit,
    val onDismiss: () -> Unit,
)

@Composable
internal fun LedgerToolsSheet(
    state: LedgerToolsSheetState,
    actions: LedgerToolsSheetActions,
) {
    val ledger = state.ledger
    val hasUserFilters = ledgerHasUserVisibleFilters(ledger)
    AppSheetScaffold(
        title = stringResource(R.string.ledger_tools_title),
        subtitle = stringResource(R.string.ledger_tools_subtitle),
    ) {
        // W2-B: 全局搜索已提为页头一级入口，sheet 内不再保留重复入口；
        // 本段只留当前列表的关键词筛选能力。
        LedgerSearchTools(
            query = ledger.query,
            onQueryChange = actions.onQueryChange,
        )
        LedgerToolDivider()
        LedgerFilterTools(
            state = ledger,
            onCategoryChange = actions.onCategoryChange,
            onTagChange = actions.onTagChange,
        )
        LedgerToolDivider()
        LedgerViewTools(
            selectedMode = ledger.viewMode,
            onViewModeChange = actions.onViewModeChange,
        )
        LedgerToolDivider()
        LedgerDataTools(
            state = ledger,
            canExport = state.canExport,
            onSync = actions.onSync,
            onExportCsv = actions.onExportCsv,
            onOpenLibrary = actions.onOpenLibrary,
        )
        LedgerToolsFooter(
            hasUserFilters = hasUserFilters,
            showNoExport = ledger.items.isEmpty(),
            onClearFilters = actions.onClearFilters,
            onDismiss = actions.onDismiss,
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
) {
    LedgerToolSection(title = stringResource(R.string.ledger_tools_filter_title)) {
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
            val tagOptions = buildAppTagFilterChoices(
                availableTags = state.tags,
                selectedTag = state.tagFilter,
            )
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
private fun LedgerSearchTools(
    query: String,
    onQueryChange: (String) -> Unit,
) {
    LedgerToolSection(title = stringResource(R.string.ledger_tools_search_title)) {
        AppTextInput(
            state = AppTextInputState(
                label = stringResource(R.string.ledger_tools_search_label),
                value = query,
                placeholder = stringResource(R.string.ledger_tools_search_placeholder),
            ),
            actions = AppTextInputActions(onValueChange = onQueryChange),
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

@Composable
private fun LedgerDataTools(
    state: LedgerUiState,
    canExport: Boolean,
    onSync: () -> Unit,
    onExportCsv: () -> Unit,
    onOpenLibrary: () -> Unit,
) {
    LedgerToolSection(title = stringResource(R.string.ledger_tools_actions_title)) {
        LedgerInlineButton(
            text = stringResource(R.string.ledger_tools_library),
            modifier = Modifier.fillMaxWidth(),
            enabled = true,
            onClick = onOpenLibrary,
            icon = Icons.Default.Category,
        )
        AppAdaptiveEqualControlRow(
            leading = { actionModifier ->
                LedgerInlineButton(
                    text = if (state.exporting) {
                        stringResource(R.string.ledger_tools_exporting)
                    } else {
                        stringResource(R.string.ledger_tools_export)
                    },
                    modifier = actionModifier,
                    enabled = canExport,
                    onClick = onExportCsv,
                    icon = Icons.Default.FileDownload,
                )
            },
            trailing = { actionModifier ->
                LedgerInlineButton(
                    text = if (state.syncing) {
                        stringResource(R.string.ledger_tools_syncing)
                    } else {
                        stringResource(R.string.ledger_tools_update_ledger)
                    },
                    modifier = actionModifier,
                    enabled = !state.syncing,
                    onClick = onSync,
                    icon = Icons.Default.Sync,
                )
            },
        )
        if (state.dataQualityFilter != null) {
            Text(
                text = stringResource(R.string.ledger_tools_export_data_quality_filtered),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
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
        if (hasUserFilters) {
            AppAdaptiveEqualControlRow(
                leading = { actionModifier ->
                    QuietOutlinedButton(
                        text = stringResource(R.string.ledger_tools_clear_filters),
                        modifier = actionModifier,
                        onClick = onClearFilters,
                    )
                },
                trailing = { actionModifier ->
                    Button(
                        modifier = actionModifier,
                        onClick = onDismiss,
                    ) {
                        Text(stringResource(R.string.ledger_tools_done))
                    }
                },
            )
        } else {
            Button(
                modifier = Modifier.fillMaxWidth(),
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

@Immutable
private data class LedgerOptionListState(
    val title: String,
    val allLabel: String,
    val options: List<String>,
    val selectedValue: String,
    val labelPrefix: String = "",
)

/**
 * W2-B: 分类/标签选择从整行单选长清单改为紧凑 chip 流——13 个默认分类 +
 * 标签不再把视图/导出/资料库挤出两屏。选中语义不变（空值=全部）。
 */
@OptIn(ExperimentalLayoutApi::class)
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
        FlowRow(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
        ) {
            AppFilterChip(
                label = state.allLabel,
                selected = state.selectedValue.isBlank(),
                onClick = { onValueChange("") },
            )
            state.options.forEach { option ->
                AppFilterChip(
                    label = "${state.labelPrefix}$option",
                    selected = state.selectedValue == option,
                    onClick = { onValueChange(option) },
                )
            }
        }
    }
}
