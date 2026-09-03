package com.ticketbox.ui.screens.recurring

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Restore
import androidx.compose.material3.AssistChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.ui.components.AppAdaptiveAmountRowDefaults
import com.ticketbox.ui.components.AppAdaptiveAmountRowStyle
import com.ticketbox.ui.components.AppAdaptiveEditAmountRow
import com.ticketbox.ui.components.AppAmountText
import com.ticketbox.ui.components.AppErrorState
import com.ticketbox.ui.components.AppListStateContent
import com.ticketbox.ui.components.AppListStateSpec
import com.ticketbox.ui.components.AppSectionGroup
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.screens.ReadableListBodyState
import com.ticketbox.ui.screens.RecurringItemActions
import com.ticketbox.ui.screens.RecurringListSectionModel

/** 页面唯一焦点：每月固定支出计划总额。只计 active 已发布 baseline，待同步不进这里。 */
@Composable
internal fun RecurringHeroSection(
    model: RecurringHeroModel,
    currencyDisplay: CurrencyDisplay,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        Text(
            text = stringResource(R.string.recurring_hero_label),
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        if (model.factual) {
            AppAmountText(
                modifier = Modifier.fillMaxWidth(),
                text = formatDisplayAmount(model.totalCents, currencyDisplay),
                color = MaterialTheme.colorScheme.onSurface,
                role = AppAmountRole.Hero,
                minFontSize = 22.sp,
            )
            Text(
                text = model.nearestNextDate?.let {
                    stringResource(
                        R.string.recurring_hero_meta_next,
                        model.activeCount,
                        recurringDisplayDate(it),
                    )
                } ?: stringResource(R.string.recurring_hero_meta, model.activeCount),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        } else {
            Text(
                text = stringResource(R.string.recurring_hero_unavailable),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.soft))
    }
}

internal data class RecurringItemsCardState(
    val title: String,
    val section: RecurringListSectionModel<RecurringItem>,
    val currencyDisplay: CurrencyDisplay,
    val canModify: Boolean,
    val editEnabled: Boolean,
)

private data class RecurringItemInteraction(
    val editEnabled: Boolean,
    val onEdit: (RecurringItem) -> Unit,
)

@Composable
internal fun RecurringItemsCard(
    state: RecurringItemsCardState,
    onRetry: () -> Unit,
    onEdit: (RecurringItem) -> Unit,
    actions: RecurringItemActions,
) {
    val visuals = LocalThemeVisuals.current
    val items = state.section.rows
    val interaction = RecurringItemInteraction(state.editEnabled, onEdit)
    AppSectionGroup(
        contentPadding = PaddingValues(vertical = AppSpacing.contentGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap)) {
            RecurringItemsCardHeader(state, items.size)
            when (state.section.bodyState) {
                ReadableListBodyState.LoadFailed -> AppErrorState(
                    title = stringResource(R.string.recurring_items_load_failed_title),
                    body = stringResource(R.string.recurring_items_load_failed_body),
                    onRetry = onRetry,
                )
                ReadableListBodyState.Loading,
                ReadableListBodyState.Empty,
                ReadableListBodyState.Content -> AppListStateContent(
                    state = AppListStateSpec(
                        isEmpty = state.section.bodyState != ReadableListBodyState.Content,
                        loading = state.section.bodyState == ReadableListBodyState.Loading,
                        emptyText = stringResource(R.string.recurring_items_empty),
                        skeletonRows = 4,
                    ),
                ) {
                    items.forEachIndexed { index, item ->
                        if (index > 0) HorizontalDivider(color = visuals.chipUnselected.copy(alpha = 0.72f))
                        RecurringItemRow(
                            item = item,
                            currencyDisplay = state.currencyDisplay,
                            canModify = state.canModify,
                            interaction = interaction,
                            actions = actions,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun RecurringItemsCardHeader(state: RecurringItemsCardState, itemCount: Int) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = stringResource(R.string.recurring_items_card_title, state.title),
            style = MaterialTheme.typography.titleMedium,
            fontWeight = AppTextHierarchy.heading.weight,
        )
        Text(
            text = when (state.section.bodyState) {
                ReadableListBodyState.Loading -> stringResource(R.string.recurring_items_card_count_loading)
                ReadableListBodyState.LoadFailed -> stringResource(R.string.recurring_items_card_count_unavailable)
                ReadableListBodyState.Empty,
                ReadableListBodyState.Content -> stringResource(R.string.recurring_items_card_count, itemCount)
            },
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelMedium,
        )
    }
}

/**
 * 列表第一眼：名称、每月计划金额、下次日期、状态。baseline 永远是计划金额，
 * 不显示 last_amount；观察 meta（次数/最近）仅 occurrenceCount>0 时降层级露出。
 * W2-C：行本体即编辑入口（active/paused）；暂停/恢复/归档收成行尾安静图标钮，
 * 不再每条目三个整行大按钮。
 */
@Composable
private fun RecurringItemRow(
    item: RecurringItem,
    currencyDisplay: CurrencyDisplay,
    canModify: Boolean,
    interaction: RecurringItemInteraction,
    actions: RecurringItemActions,
) {
    val meta = recurringItemMeta(item)
    val archived = item.status == "archived"
    val capabilities = recurringRowCapabilities(item.status)
    val editable = canModify && capabilities.editable && interaction.editEnabled
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .then(
                if (editable) {
                    Modifier.clickable(role = Role.Button) { interaction.onEdit(item) }
                } else {
                    Modifier
                },
            )
            .then(if (archived) Modifier.alpha(AppAlpha.opaque) else Modifier),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        AppAdaptiveEditAmountRow(
            amount = formatDisplayAmount(item.baselineAmountCents, currencyDisplay),
            style = AppAdaptiveAmountRowStyle(
                role = AppAmountRole.Compact,
                trailingWeight = AppAdaptiveAmountRowDefaults.listTrailingWeight,
            ),
        ) {
            RecurringItemMetaColumn(item = item, meta = meta)
        }
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(modifier = Modifier.weight(1f)) { RecurringStatusChips(item, meta) }
            if (canModify) {
                RecurringRowIconActions(item = item, capabilities = capabilities, actions = actions)
            }
        }
    }
}

@Composable
private fun RecurringItemMetaColumn(item: RecurringItem, meta: RecurringItemMeta) {
    val merchantFallback = stringResource(R.string.recurring_item_merchant_fallback)
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
        Text(
            text = item.merchant.ifBlank { merchantFallback },
            style = MaterialTheme.typography.bodyLarge,
            fontWeight = FontWeight.SemiBold,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Text(
            text = recurringNextDateText(meta),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        meta.observedCount?.let { count ->
            Text(
                text = meta.lastObservedDate?.let {
                    stringResource(R.string.recurring_meta_observed_last, count, recurringDisplayDate(it))
                } ?: stringResource(R.string.recurring_meta_observed_count, count),
                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = AppAlpha.heavy),
                style = MaterialTheme.typography.labelSmall,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
private fun recurringNextDateText(meta: RecurringItemMeta): String =
    meta.nextExpectedDate?.let {
        stringResource(R.string.recurring_meta_next, recurringDisplayDate(it))
    } ?: stringResource(
        if (meta.observedCount != null) {
            R.string.recurring_meta_next_unknown
        } else {
            R.string.recurring_meta_next_no_reminder
        },
    )

/** 行尾安静生命周期动作（图标级）：active→暂停、paused→恢复，且均可归档；archived→恢复。 */
@Composable
private fun RecurringRowIconActions(
    item: RecurringItem,
    capabilities: RecurringRowCapabilities,
    actions: RecurringItemActions,
) {
    Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
        when {
            capabilities.restorable -> RecurringQuietIconAction(
                icon = Icons.Filled.Restore,
                description = stringResource(R.string.recurring_action_restore_description),
                onClick = { actions.onRestore(item.publicId, item.rowVersion) },
            )
            capabilities.lifecycleActions -> {
                if (item.status == "active") {
                    RecurringQuietIconAction(
                        icon = Icons.Filled.Pause,
                        description = stringResource(R.string.recurring_action_pause_description),
                        onClick = { actions.onPause(item.publicId, item.rowVersion) },
                    )
                } else {
                    RecurringQuietIconAction(
                        icon = Icons.Filled.PlayArrow,
                        description = stringResource(R.string.recurring_action_resume_description),
                        onClick = { actions.onResume(item.publicId, item.rowVersion) },
                    )
                }
                RecurringQuietIconAction(
                    icon = Icons.Filled.DeleteOutline,
                    description = stringResource(R.string.recurring_action_archive_description),
                    onClick = { actions.onArchive(item.publicId) },
                )
            }
        }
    }
}

/** 安静图标钮：onSurfaceVariant 单色，不抢行内金额/状态层级；contentDescription 双态都在。 */
@Composable
private fun RecurringQuietIconAction(
    icon: ImageVector,
    description: String,
    onClick: () -> Unit,
) {
    IconButton(onClick = onClick) {
        Icon(
            imageVector = icon,
            contentDescription = description,
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun RecurringStatusChips(item: RecurringItem, meta: RecurringItemMeta) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        RecurringStatusChip(item.status)
        meta.anomalyDeltaPercent?.let { delta ->
            AssistChip(
                onClick = {},
                label = { Text(stringResource(R.string.recurring_item_anomaly_higher, delta)) },
            )
        }
    }
}

@Composable
private fun RecurringStatusChip(status: String) {
    val visuals = LocalThemeVisuals.current
    val label = when (status) {
        "active" -> stringResource(R.string.recurring_status_active)
        "paused" -> stringResource(R.string.recurring_status_paused)
        "archived" -> stringResource(R.string.recurring_status_archived)
        else -> status
    }
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(AppRadius.pill))
            .background(visuals.chipSelected.copy(alpha = if (status == "active") 0.95f else 0.58f))
            .padding(horizontal = AppSpacing.smallGap, vertical = AppSpacing.tinyGap + 1.dp),
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.labelSmall,
            fontWeight = FontWeight.SemiBold,
        )
    }
}
