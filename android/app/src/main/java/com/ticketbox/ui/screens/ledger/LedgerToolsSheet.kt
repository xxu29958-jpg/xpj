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
import androidx.compose.material.icons.filled.Category
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.FileDownload
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
import com.ticketbox.ui.components.AppAdaptiveEqualControlRow
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.ui.components.AppSegmentedControl
import com.ticketbox.ui.components.AppSegmentedItem
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.components.buildAppTagFilterChoices
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalThemeVisuals
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
    val onOpenGlobalSearch: () -> Unit,
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
        LedgerSearchTools(
            query = ledger.query,
            onQueryChange = actions.onQueryChange,
            onOpenGlobalSearch = actions.onOpenGlobalSearch,
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
    onOpenGlobalSearch: () -> Unit,
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
