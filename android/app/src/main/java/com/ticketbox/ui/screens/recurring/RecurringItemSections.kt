package com.ticketbox.ui.screens.recurring

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.CalendarMonth
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.MoreHoriz
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import com.ticketbox.R
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.ui.components.AppAdaptiveAmountRowDefaults
import com.ticketbox.ui.components.AppAdaptiveAmountRowStyle
import com.ticketbox.ui.components.AppAdaptiveEditAmountRow
import com.ticketbox.ui.components.AppAdaptiveContentActionRow
import com.ticketbox.ui.components.AppAdaptiveContentActionStyle
import com.ticketbox.ui.components.AppAmountText
import com.ticketbox.ui.components.AppErrorState
import com.ticketbox.ui.components.AppListStateContent
import com.ticketbox.ui.components.AppListStateSpec
import com.ticketbox.ui.components.AppSectionGroup
import com.ticketbox.ui.components.SettingsEntryIcon
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppIconSize
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.screens.ReadableListBodyState
import com.ticketbox.ui.screens.RecurringItemActions
import com.ticketbox.ui.screens.RecurringListSectionModel
import java.time.LocalDate

/** 正式计划摘要：保留原币合计，只计 active 已发布 baseline，待同步不计入。 */
@Composable
internal fun RecurringHeroSection(
    model: RecurringHeroModel,
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
            recurringTotalLines(model).forEach { amount ->
                AppAmountText(
                    modifier = Modifier.fillMaxWidth(),
                    text = amount,
                    color = MaterialTheme.colorScheme.onSurface,
                    role = AppAmountRole.Compact,
                    minFontSize = 14.sp,
                )
            }
            Text(
                text = model.nearestNextDate?.let {
                    stringResource(
                        when (recurringDueIsPast(it, model.ledgerToday)) {
                            true -> R.string.recurring_hero_meta_past
                            false -> R.string.recurring_hero_meta_next
                            null -> R.string.recurring_hero_meta_expected
                        },
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
/** The list is the primary surface; totals and online read provenance remain available on demand. */
@Composable
internal fun RecurringOverviewDetails(model: RecurringHeroModel, readSource: @Composable () -> Unit) {
    var expanded by rememberSaveable { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        TextButton(onClick = { expanded = !expanded }) {
            Text(stringResource(R.string.recurring_overview_details))
            Icon(if (expanded) Icons.Filled.ExpandLess else Icons.Filled.ExpandMore, contentDescription = null)
        }
        if (expanded) {
            RecurringHeroSection(model)
            Text(stringResource(R.string.recurring_plan_notice), style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            readSource()
        }
    }
}

internal data class RecurringItemsCardState(
    val title: String,
    val section: RecurringListSectionModel<RecurringItem>,
    val canModify: Boolean,
    val editEnabled: Boolean,
    val ledgerToday: LocalDate? = null,
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
    filter: @Composable () -> Unit,
) {
    val visuals = LocalThemeVisuals.current
    val items = state.section.rows
    val interaction = RecurringItemInteraction(state.editEnabled, onEdit)
    AppSectionGroup(
        contentPadding = PaddingValues(vertical = AppSpacing.contentGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        showTopDivider = false,
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap)) {
            AppAdaptiveContentActionRow(
                style = AppAdaptiveContentActionStyle(compactAction = true),
                content = {
                    Text(state.title, style = MaterialTheme.typography.titleMedium,
                        fontWeight = AppTextHierarchy.heading.weight)
                },
                action = { filter() },
            )
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
                            canModify = state.canModify,
                            interaction = interaction,
                            actions = actions,
                            meta = recurringItemMeta(item, state.ledgerToday),
                        )
                    }
                }
            }
        }
    }
}

/**
 * v0.6 plan row: the original editor stays on the row; payment, history and lifecycle
 * commands share its overflow menu. Published amounts and due dates stay in the first line of reading.
 */
@Composable
private fun RecurringItemRow(
    item: RecurringItem,
    canModify: Boolean,
    interaction: RecurringItemInteraction,
    actions: RecurringItemActions,
    meta: RecurringItemMeta,
) {
    val archived = item.status == "archived"
    val capabilities = recurringRowCapabilities(item.status)
    val editable = canModify && capabilities.editable && interaction.editEnabled
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .testTag("recurring-item-" + item.publicId)
            .padding(vertical = AppSpacing.contentGap)
            .then(
                if (editable) {
                    Modifier.clickable(role = Role.Button) { interaction.onEdit(item) }
                } else {
                    Modifier
                },
            )
            .then(if (archived) Modifier.alpha(AppAlpha.opaque) else Modifier),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        SettingsEntryIcon(Icons.Outlined.CalendarMonth)
        AppAdaptiveEditAmountRow(
            modifier = Modifier.weight(1f),
            amount = recurringRecordedAmountText(item.baselineAmountCents, item.homeCurrencyCode),
            style = AppAdaptiveAmountRowStyle(
                role = AppAmountRole.Compact,
                trailingWeight = AppAdaptiveAmountRowDefaults.listTrailingWeight,
            ),
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
                RecurringItemMetaColumn(item = item, meta = meta)
                if (item.status != "active" || meta.anomalyDeltaPercent != null) {
                    RecurringStatusChips(item, meta)
                }
            }
        }
        RecurringRowMenu(item, canModify, actions)
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
        )
        Text(
            text = recurringNextDateText(meta),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
        meta.observedCount?.let { count ->
            Text(
                text = meta.lastObservedDate?.let {
                    stringResource(R.string.recurring_meta_observed_last, count, recurringDisplayDate(it))
                } ?: stringResource(R.string.recurring_meta_observed_count, count),
                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = AppAlpha.heavy),
                style = MaterialTheme.typography.labelSmall,
            )
        }
    }
}

@Composable
private fun recurringNextDateText(meta: RecurringItemMeta): String =
    meta.nextExpectedDate?.let {
        stringResource(
            when (recurringDueIsPast(it, meta.ledgerToday)) {
                true -> R.string.recurring_meta_next_past
                false -> R.string.recurring_meta_next
                null -> R.string.recurring_meta_expected
            },
            recurringDisplayDate(it),
        )
    } ?: stringResource(
        if (meta.observedCount != null) {
            R.string.recurring_meta_next_unknown
        } else {
            R.string.recurring_meta_next_no_reminder
        },
    )

@Composable
private fun RecurringRowMenu(
    item: RecurringItem,
    canModify: Boolean,
    actions: RecurringItemActions,
) {
    var expanded by rememberSaveable(item.publicId) { mutableStateOf(false) }
    val capabilities = recurringRowCapabilities(item.status)
    Box {
        IconButton(modifier = Modifier.testTag("recurring-actions-" + item.publicId), onClick = { expanded = true }) {
            Icon(Icons.Filled.MoreHoriz, contentDescription = stringResource(R.string.recurring_more_actions, item.merchant),
                tint = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.size(AppIconSize.compact))
        }
        DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            DropdownMenuItem(text = { Text(stringResource(R.string.occurrence_open)) }, onClick = {
                expanded = false
                actions.onOpenOccurrence(item)
            })
            actions.onOpenHistory?.let { open ->
                DropdownMenuItem(text = { Text(stringResource(R.string.recurring_history_title)) }, onClick = {
                    expanded = false
                    open(item)
                })
            }
            if (canModify && capabilities.restorable) {
                DropdownMenuItem(text = { Text(stringResource(R.string.recurring_action_restore_description)) }, onClick = {
                    expanded = false
                    actions.onRestore(item.publicId, item.rowVersion)
                })
            }
            if (canModify && capabilities.lifecycleActions) {
                val active = item.status == "active"
                DropdownMenuItem(text = { Text(stringResource(if (active) R.string.recurring_action_pause_description
                    else R.string.recurring_action_resume_description)) }, onClick = {
                    expanded = false
                    if (active) actions.onPause(item.publicId, item.rowVersion) else actions.onResume(item.publicId, item.rowVersion)
                })
                DropdownMenuItem(text = { Text(stringResource(R.string.recurring_action_archive_description)) }, onClick = {
                    expanded = false
                    actions.onArchive(item.publicId)
                })
            }
        }
    }
}

@Composable
private fun RecurringStatusChips(item: RecurringItem, meta: RecurringItemMeta) {
    FlowRow(
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
    ) {
        if (item.status != "active") {
            val label = when (item.status) {
                "paused" -> stringResource(R.string.recurring_status_paused)
                "archived" -> stringResource(R.string.recurring_status_archived)
                else -> item.status
            }
            Text(label, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        meta.anomalyDeltaPercent?.let { delta ->
            Text(stringResource(R.string.recurring_item_anomaly_higher, delta),
                style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.error)
        }
    }
}
