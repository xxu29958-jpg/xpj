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
import androidx.compose.foundation.layout.widthIn
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
import com.ticketbox.ui.design.AppWindowWidthClass
import com.ticketbox.ui.design.LocalAppAdaptiveLayoutPolicy
import com.ticketbox.ui.design.LocalStatsTokens
import com.ticketbox.viewmodel.StatsUiState

private const val StatsTagFilterOptionLimit = 12

/** 筛选 pill 的最大宽度：长标签名 ellipsize，控件固有宽度，不再随窗拉伸。 */
private val StatsFilterPillMaxWidth = 232.dp

/** Medium+ 页签固有宽度的下限：触控宽度始终高于可访问底线（高度仍由 48dp controlMinHeight 保证）。 */
private val StatsTabMinWidth = 64.dp

/**
 * 月份/标签筛选：固有宽度、行首对齐，紧贴它影响的结果列表。
 * 标签 Loading/Failed/Hidden 状态与选项上限原样保留；48dp 触控高度不变。
 */
@Composable
internal fun StatsFilterControls(
    state: StatsUiState,
    onOpenMonthPicker: () -> Unit,
    onTagChange: (String) -> Unit,
) {
    val tagControl = statsTagFilterControlModel(
        state = state,
        optionLimit = StatsTagFilterOptionLimit,
    )
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        StatsSelectablePill(
            selected = true,
            onClick = onOpenMonthPicker,
            label = state.month.takeIf { it.isNotBlank() }?.let { displayMonthLabel(it) }
                ?: stringResource(R.string.stats_filter_all_months),
            modifier = Modifier.widthIn(max = StatsFilterPillMaxWidth),
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
                modifier = Modifier.widthIn(max = StatsFilterPillMaxWidth),
            )
            StatsTagFilterControlKind.Loading -> StatsTagStatusPill(
                label = stringResource(R.string.stats_filter_tags_loading),
                modifier = Modifier.widthIn(max = StatsFilterPillMaxWidth),
            )
            StatsTagFilterControlKind.Failed -> StatsTagStatusPill(
                label = stringResource(R.string.stats_filter_tags_load_failed),
                modifier = Modifier.widthIn(max = StatsFilterPillMaxWidth),
            )
            StatsTagFilterControlKind.Hidden -> Unit
        }
    }
}

/**
 * 概览/趋势/构成页签：Compact 等宽（拇指分区），Medium+ 固有宽度行首对齐，
 * 不再横跨整个窗口；始终紧贴它切换的结果内容。
 */
@Composable
internal fun StatsViewTabs(
    selectedTab: StatsTab,
    onTabChange: (StatsTab) -> Unit,
) {
    val fillWindow = LocalAppAdaptiveLayoutPolicy.current.widthClass == AppWindowWidthClass.Compact
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
                modifier = if (fillWindow) {
                    Modifier.weight(1f)
                } else {
                    Modifier.widthIn(min = StatsTabMinWidth)
                },
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
