package com.ticketbox.ui.screens.recurring

import androidx.compose.foundation.background
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
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Restore
import androidx.compose.material3.AssistChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.ui.components.AppAdaptiveAmountRowDefaults
import com.ticketbox.ui.components.AppAdaptiveAmountRowStyle
import com.ticketbox.ui.components.AppAdaptiveContentActionRow
import com.ticketbox.ui.components.AppAdaptiveEditActionLayout
import com.ticketbox.ui.components.AppAdaptiveEditActionMode
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
    AppSectionGroup(
        contentPadding = PaddingValues(vertical = AppSpacing.contentGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap)) {
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
                        ReadableListBodyState.Content -> stringResource(R.string.recurring_items_card_count, items.size)
                    },
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.labelMedium,
                )
            }
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
                            onEdit = onEdit,
                            actions = actions,
                        )
                    }
                }
            }
        }
    }
}

/**
 * 列表第一眼：名称、每月计划金额、下次日期、状态。baseline 永远是计划金额，
 * 不显示 last_amount；观察 meta（次数/最近）仅 occurrenceCount>0 时降层级露出。
 */
@Composable
private fun RecurringItemRow(
    item: RecurringItem,
    currencyDisplay: CurrencyDisplay,
    canModify: Boolean,
    onEdit: (RecurringItem) -> Unit,
    actions: RecurringItemActions,
) {
    val meta = recurringItemMeta(item)
    val archived = item.status == "archived"
    Column(
        modifier = Modifier.then(if (archived) Modifier.alpha(AppAlpha.opaque) else Modifier),
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
        if (canModify) {
            AppAdaptiveContentActionRow(
                wideActionWeight = 0.92f,
                content = { RecurringStatusChips(item, meta) },
                action = { actionModifier ->
                    RecurringRowActions(
                        modifier = actionModifier,
                        item = item,
                        onEdit = onEdit,
                        actions = actions,
                    )
                },
            )
        } else {
            RecurringStatusChips(item, meta)
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

@Composable
private fun RecurringRowActions(
    modifier: Modifier = Modifier,
    item: RecurringItem,
    onEdit: (RecurringItem) -> Unit,
    actions: RecurringItemActions,
) {
    val capabilities = recurringRowCapabilities(item.status)
    AppAdaptiveEditActionLayout(
        actionCount = if (capabilities.lifecycleActions) 3 else 1,
        compact = false,
        modifier = modifier,
        stackTwoActionsOnNarrow = true,
    ) { mode ->
        if (mode == AppAdaptiveEditActionMode.Stacked) {
            Column(
                modifier = Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
            ) {
                RecurringRowActionButtons(
                    item = item,
                    capabilities = capabilities,
                    onEdit = onEdit,
                    actions = actions,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        } else {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.miniGap, Alignment.End),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                RecurringRowActionButtons(
                    item = item,
                    capabilities = capabilities,
                    onEdit = onEdit,
                    actions = actions,
                    modifier = Modifier,
                )
            }
        }
    }
}

@Composable
private fun RecurringRowActionButtons(
    item: RecurringItem,
    capabilities: RecurringRowCapabilities,
    onEdit: (RecurringItem) -> Unit,
    actions: RecurringItemActions,
    modifier: Modifier = Modifier,
) {
    if (capabilities.editable) {
        TextButton(modifier = modifier, onClick = { onEdit(item) }) {
            Icon(
                Icons.Filled.Edit,
                contentDescription = stringResource(R.string.recurring_action_edit_description),
            )
            Text(stringResource(R.string.recurring_action_edit))
        }
    }
    if (capabilities.lifecycleActions) {
        when (item.status) {
            "active" -> TextButton(
                modifier = modifier,
                onClick = { actions.onPause(item.publicId, item.rowVersion) },
            ) {
                Text(stringResource(R.string.recurring_action_pause))
            }
            "paused" -> TextButton(
                modifier = modifier,
                onClick = { actions.onResume(item.publicId, item.rowVersion) },
            ) {
                Text(stringResource(R.string.recurring_action_resume))
            }
        }
        TextButton(modifier = modifier, onClick = { actions.onArchive(item.publicId) }) {
            Icon(
                Icons.Filled.DeleteOutline,
                contentDescription = stringResource(R.string.recurring_action_archive_description),
            )
            Text(stringResource(R.string.recurring_action_archive))
        }
    }
    if (capabilities.restorable) {
        TextButton(
            modifier = modifier,
            onClick = { actions.onRestore(item.publicId, item.rowVersion) },
        ) {
            Icon(
                Icons.Filled.Restore,
                contentDescription = stringResource(R.string.recurring_action_restore_description),
            )
            Text(stringResource(R.string.recurring_action_restore))
        }
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
