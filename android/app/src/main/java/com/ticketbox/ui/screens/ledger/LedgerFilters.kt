package com.ticketbox.ui.screens.ledger

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowLeft
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Icon
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.TextButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppOutlinedButton
import com.ticketbox.ui.components.AppOutlinedButtonOptions
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.screens.LedgerRecordCtaSlot
import com.ticketbox.viewmodel.LedgerUiState

private object LedgerFilterLayout {
    val StepIconSize = 20.dp
    val InlineIconSize = 18.dp
}

@Composable
internal fun LedgerFilterPanel(
    state: LedgerUiState,
    actions: LedgerFilterPanelActions,
    recordCtaSlot: LedgerRecordCtaSlot?,
    showSummaryHeader: Boolean = true,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        LedgerInlineFilters(
            state = state,
            recordCtaSlot = recordCtaSlot,
            actions = actions,
        )
        if (showSummaryHeader) LedgerHeader(state = state)
    }
}

internal data class LedgerFilterPanelActions(
    val onOpenMonthPicker: () -> Unit,
    val onOpenTools: () -> Unit,
    val onOpenSearch: () -> Unit,
    val onManualAdd: () -> Unit,
    val onCategoryChange: (String) -> Unit,
)

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun LedgerInlineFilters(
    state: LedgerUiState,
    recordCtaSlot: LedgerRecordCtaSlot?,
    actions: LedgerFilterPanelActions,
) {
    val activeFilterCount = ledgerActiveFilterCount(state)
    FlowRow(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        AppFilterChip(
            label = displayMonthLabel(state.monthFilter).takeIf { state.monthFilter.isNotBlank() }
                ?: stringResource(R.string.ledger_inline_month_all),
            selected = state.monthFilter.isNotBlank(),
            onClick = actions.onOpenMonthPicker,
        )
        LedgerCategoryFilter(state = state, onCategoryChange = actions.onCategoryChange)
        AppFilterChip(
            label = if (activeFilterCount == 0) stringResource(R.string.ledger_inline_filter)
                else stringResource(R.string.ledger_inline_filter_count, activeFilterCount),
            selected = activeFilterCount > 0,
            onClick = actions.onOpenTools,
        )
        LedgerChromeIconButton(
            icon = Icons.Filled.Search,
            description = stringResource(R.string.global_search_header_title),
            onClick = actions.onOpenSearch,
        )
        // 原单一录入槽保留；空态由空态动作承担，只读没有写入口。
        if (recordCtaSlot == LedgerRecordCtaSlot.Header) {
            TextButton(onClick = actions.onManualAdd) {
                Icon(Icons.Filled.Add, contentDescription = null,
                    modifier = Modifier.size(LedgerFilterLayout.InlineIconSize))
                Text(stringResource(R.string.ledger_header_add_button))
            }
        }
    }
}

@Composable
private fun LedgerCategoryFilter(state: LedgerUiState, onCategoryChange: (String) -> Unit) {
    var expanded by rememberSaveable { mutableStateOf(false) }
    val options = (listOf(state.categoryFilter) + state.categories).filter { it.isNotBlank() }.distinct()
    Box {
        AppFilterChip(
            label = state.categoryFilter.ifBlank { stringResource(R.string.ledger_inline_category_all) },
            selected = state.categoryFilter.isNotBlank(),
            onClick = { expanded = true },
        )
        DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            DropdownMenuItem(
                text = { Text(stringResource(R.string.ledger_inline_category_all)) },
                onClick = { onCategoryChange(""); expanded = false },
            )
            options.forEach { category ->
                DropdownMenuItem(
                    text = { Text(category) },
                    onClick = { onCategoryChange(category); expanded = false },
                )
            }
        }
    }
}

private fun ledgerActiveFilterCount(state: LedgerUiState): Int {
    var count = 0
    if (state.categoryFilter.isNotBlank()) count += 1
    if (state.tagFilter.isNotBlank()) count += 1
    if (state.query.isNotBlank()) count += 1
    if (state.dataQualityFilter != null) count += 1
    return count
}

@Immutable
internal data class LedgerMonthStepperState(
    val label: String,
    val previousMonth: String?,
    val nextMonth: String?,
)

@Composable
internal fun LedgerMonthStepper(
    state: LedgerMonthStepperState,
    onMonthChange: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier
            .heightIn(min = AppSpacing.controlMinHeight)
            .padding(vertical = AppSpacing.tinyGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        LedgerMonthStepButton(
            icon = Icons.AutoMirrored.Filled.KeyboardArrowLeft,
            description = stringResource(R.string.ledger_inline_month_prev),
            enabled = state.previousMonth != null,
            onClick = { state.previousMonth?.let(onMonthChange) },
        )
        Text(
            text = state.label,
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.labelLarge,
            fontWeight = AppTextHierarchy.heading.weight,
            modifier = Modifier.weight(1f),
            textAlign = TextAlign.Center,
        )
        LedgerMonthStepButton(
            icon = Icons.AutoMirrored.Filled.KeyboardArrowRight,
            description = stringResource(R.string.ledger_inline_month_next),
            enabled = state.nextMonth != null,
            onClick = { state.nextMonth?.let(onMonthChange) },
        )
    }
}

@Composable
private fun LedgerMonthStepButton(
    icon: ImageVector,
    description: String,
    enabled: Boolean,
    onClick: () -> Unit,
) {
    Box(
        modifier = Modifier
            .size(AppSpacing.controlMinHeight)
            .alpha(if (enabled) 1f else 0.36f)
            .clip(RoundedCornerShape(AppRadius.extraSmall))
            .clickable(enabled = enabled, role = Role.Button, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Icon(
            imageVector = icon,
            contentDescription = description,
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.size(LedgerFilterLayout.StepIconSize),
        )
    }
}

@Composable
private fun LedgerChromeIconButton(
    icon: ImageVector,
    description: String,
    onClick: () -> Unit,
) {
    Box(
        modifier = Modifier
            .size(AppSpacing.controlMinHeight)
            .clip(RoundedCornerShape(AppRadius.extraSmall))
            .clickable(role = Role.Button, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Icon(
            imageVector = icon,
            contentDescription = description,
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.size(LedgerFilterLayout.StepIconSize),
        )
    }
}

@Composable
internal fun LedgerInlineButton(
    text: String,
    modifier: Modifier,
    enabled: Boolean,
    onClick: () -> Unit,
    icon: ImageVector? = null,
) {
    AppOutlinedButton(
        modifier = modifier.heightIn(min = AppSpacing.controlMinHeight),
        onClick = onClick,
        options = AppOutlinedButtonOptions(
            enabled = enabled,
            contentPadding = PaddingValues(
                horizontal = AppSpacing.compactPadding,
                vertical = AppSpacing.none,
            ),
        ),
    ) {
        if (icon != null) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                modifier = Modifier.size(LedgerFilterLayout.InlineIconSize),
            )
        }
        Text(
            text = text,
            modifier = if (icon == null) Modifier else Modifier.padding(start = AppSpacing.miniGap),
            maxLines = 1,
            softWrap = false,
            overflow = TextOverflow.Ellipsis,
        )
    }
}
