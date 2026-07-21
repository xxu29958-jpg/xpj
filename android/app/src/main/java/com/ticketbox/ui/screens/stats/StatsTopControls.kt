package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.PrimaryStatsTabs
import com.ticketbox.domain.model.StatsTab
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStatsTokens
import com.ticketbox.viewmodel.StatsUiState

private const val StatsTagFilterOptionLimit = 12

internal data class StatsTopPanelActions(
    val onOpenMonthPicker: () -> Unit,
    val onTagChange: (String) -> Unit,
    val onTabChange: (StatsTab) -> Unit,
)

@Composable
internal fun StatsTopPanel(
    state: StatsUiState,
    selectedTab: StatsTab,
    actions: StatsTopPanelActions,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        StatsHeader()
        StatsFilterRow(
            state = state,
            onOpenMonthPicker = actions.onOpenMonthPicker,
            onTagChange = actions.onTagChange,
        )
        StatsTabRow(
            selectedTab = selectedTab,
            onTabChange = actions.onTabChange,
        )
    }
}

@Composable
private fun StatsHeader() {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
        ) {
            Text(
                text = stringResource(R.string.stats_header_title),
                color = MaterialTheme.colorScheme.onSurface,
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                text = stringResource(R.string.stats_header_subtitle),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
private fun StatsTabRow(
    selectedTab: StatsTab,
    onTabChange: (StatsTab) -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .selectableGroup(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        PrimaryStatsTabs.forEach { tab ->
            StatsTextTab(
                label = statsTabLabel(tab),
                selected = selectedTab == tab,
                modifier = Modifier.weight(1f),
                onClick = { onTabChange(tab) },
            )
        }
    }
}

@Composable
private fun statsTabLabel(tab: StatsTab): String = when (tab) {
    StatsTab.Overview -> stringResource(R.string.stats_tab_overview)
    StatsTab.Trend -> stringResource(R.string.stats_tab_trend)
    StatsTab.Category -> stringResource(R.string.stats_tab_category)
    StatsTab.Budget -> stringResource(R.string.stats_tab_budget)
    StatsTab.Goals -> stringResource(R.string.stats_tab_goals)
}

@Composable
private fun StatsFilterRow(
    state: StatsUiState,
    onOpenMonthPicker: () -> Unit,
    onTagChange: (String) -> Unit,
) {
    val tagControl = statsTagFilterControlModel(
        state = state,
        optionLimit = StatsTagFilterOptionLimit,
    )
    if (tagControl.kind != StatsTagFilterControlKind.Hidden) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        ) {
            StatsSelectablePill(
                selected = true,
                onClick = onOpenMonthPicker,
                label = state.month.takeIf { it.isNotBlank() }?.let { displayMonthLabel(it) }
                    ?: stringResource(R.string.stats_filter_all_months),
                modifier = Modifier.weight(1f),
                trailingIcon = {
                    FilterTrailingIcon(
                        Icons.Filled.ExpandMore,
                        stringResource(R.string.stats_filter_pick_month_description),
                    )
                },
            )
            when (tagControl.kind) {
                StatsTagFilterControlKind.Menu -> StatsTagFilterMenu(
                    tags = tagControl.choices,
                    selectedTag = state.selectedTag,
                    onTagChange = onTagChange,
                    modifier = Modifier.weight(1f),
                )
                StatsTagFilterControlKind.Loading -> StatsTagStatusPill(
                    label = stringResource(R.string.stats_filter_tags_loading),
                    modifier = Modifier.weight(1f),
                )
                StatsTagFilterControlKind.Failed -> StatsTagStatusPill(
                    label = stringResource(R.string.stats_filter_tags_load_failed),
                    modifier = Modifier.weight(1f),
                )
                StatsTagFilterControlKind.Hidden -> Unit
            }
        }
    } else {
        StatsSelectablePill(
            selected = true,
            onClick = onOpenMonthPicker,
            label = state.month.takeIf { it.isNotBlank() }?.let { displayMonthLabel(it) }
                ?: stringResource(R.string.stats_filter_all_months),
            modifier = Modifier.fillMaxWidth(),
            trailingIcon = {
                FilterTrailingIcon(
                    Icons.Filled.ExpandMore,
                    stringResource(R.string.stats_filter_pick_month_description),
                )
            },
        )
    }
}

@Composable
private fun StatsTagStatusPill(
    label: String,
    modifier: Modifier = Modifier,
) {
    StatsSelectablePill(
        selected = false,
        onClick = null,
        label = label,
        modifier = modifier,
    )
}

@Composable
private fun StatsTagFilterMenu(
    tags: List<String>,
    selectedTag: String,
    onTagChange: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    var expanded by remember { mutableStateOf(false) }
    Box(modifier = modifier) {
        StatsSelectablePill(
            selected = selectedTag.isNotBlank(),
            onClick = { expanded = true },
            label = selectedTag.takeIf { it.isNotBlank() }?.let { "#$it" }
                ?: stringResource(R.string.stats_filter_all_tags),
            modifier = Modifier.fillMaxWidth(),
            trailingIcon = {
                FilterTrailingIcon(
                    Icons.Filled.ExpandMore,
                    stringResource(R.string.stats_filter_tag_menu_description),
                )
            },
        )
        DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            DropdownMenuItem(
                text = { Text(stringResource(R.string.stats_filter_all_tags)) },
                onClick = {
                    expanded = false
                    onTagChange("")
                },
            )
            tags.forEach { tag ->
                DropdownMenuItem(
                    text = { Text("#$tag") },
                    onClick = {
                        expanded = false
                        onTagChange(tag)
                    },
                )
            }
        }
    }
}

@Composable
private fun StatsTextTab(
    label: String,
    selected: Boolean,
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    val controlTokens = LocalStatsTokens.current.control
    val labelColor = if (selected) {
        MaterialTheme.colorScheme.primary
    } else {
        MaterialTheme.colorScheme.onSurfaceVariant
    }
    Column(
        modifier = modifier
            .heightIn(min = AppSpacing.controlMinHeight)
            .selectable(
                selected = selected,
                role = Role.Tab,
                onClick = onClick,
            )
            .padding(horizontal = AppSpacing.miniGap),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Box(
            modifier = Modifier.weight(1f),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                text = label,
                color = labelColor,
                style = MaterialTheme.typography.labelLarge,
                fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Medium,
                maxLines = 1,
            )
        }
        Box(
            modifier = Modifier
                .size(
                    width = StatsTabIndicatorTokens.Width,
                    height = StatsTabIndicatorTokens.Height,
                )
                .background(
                    color = if (selected) MaterialTheme.colorScheme.primary else androidx.compose.ui.graphics.Color.Transparent,
                    shape = RoundedCornerShape(AppRadius.pill),
                ),
        )
    }
}

@Composable
private fun StatsSelectablePill(
    label: String,
    selected: Boolean,
    onClick: (() -> Unit)?,
    modifier: Modifier = Modifier,
    trailingIcon: (@Composable () -> Unit)? = null,
) {
    val controlTokens = LocalStatsTokens.current.control
    val shape = RoundedCornerShape(AppRadius.small)
    val labelColor = if (selected) {
        MaterialTheme.colorScheme.primary
    } else if (onClick == null) {
        MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.62f)
    } else {
        MaterialTheme.colorScheme.onSurfaceVariant
    }
    Row(
        modifier = modifier
            .heightIn(min = AppSpacing.controlMinHeight)
            .clip(shape)
            .background(MaterialTheme.colorScheme.surface)
            .border(
                width = controlTokens.borderWidth,
                color = if (selected) {
                    MaterialTheme.colorScheme.primary.copy(alpha = 0.44f)
                } else {
                    MaterialTheme.colorScheme.outlineVariant
                },
                shape = shape,
            )
            .clickable(enabled = onClick != null, role = Role.Button, onClick = { onClick?.invoke() })
            .padding(horizontal = controlTokens.horizontalPadding),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.miniGap, Alignment.CenterHorizontally),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = label,
            modifier = Modifier.weight(1f, fill = false),
            color = labelColor,
            style = MaterialTheme.typography.labelLarge,
            fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Medium,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        trailingIcon?.invoke()
    }
}

@Composable
private fun FilterTrailingIcon(
    icon: ImageVector,
    contentDescription: String,
) {
    Icon(
        imageVector = icon,
        contentDescription = contentDescription,
        modifier = Modifier.size(AppSpacing.cardPaddingSmall),
    )
}

private object StatsTabIndicatorTokens {
    val Width = 22.dp
    val Height = 2.dp
}
