package com.ticketbox.ui.screens.transactions

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.RestoreFromTrash
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.res.vectorResource
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.domain.model.RecycleBinItem
import com.ticketbox.ui.components.AppAdaptiveContentActionRow
import com.ticketbox.ui.components.AppAdaptiveContentActionStyle
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.SettingsEntryIcon
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.components.AppContentCard
import com.ticketbox.ui.components.AppDataAuthorityStrip
import com.ticketbox.ui.components.AppErrorState
import com.ticketbox.ui.components.AppListRow
import com.ticketbox.ui.components.AppListStateContent
import com.ticketbox.ui.components.AppListStateSpec
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryRefreshState
import com.ticketbox.ui.components.AppSecondaryScrollableContent
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.DataAuthorityTone
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.viewmodel.RecycleBinUiState
import com.ticketbox.viewmodel.RecycleBinViewModel
import com.ticketbox.viewmodel.busyKey

private val planKinds = setOf("monthly_budget", "income_plan", "recurring_item", "goal")
private enum class RecycleGroup(val label: Int) {
    All(R.string.recycle_bin_group_all),
    Reference(R.string.recycle_bin_group_reference),
    Plans(R.string.recycle_bin_group_plans),
}

internal enum class RecycleBinBodyState {
    Loading,
    LoadFailed,
    Empty,
    Content,
}

internal fun recycleBinBodyState(state: RecycleBinUiState): RecycleBinBodyState = when {
    state.items.isNotEmpty() -> RecycleBinBodyState.Content
    state.loading -> RecycleBinBodyState.Loading
    state.loadFailed -> RecycleBinBodyState.LoadFailed
    else -> RecycleBinBodyState.Empty
}

internal data class RecycleBinSummaryModel(
    val totalCount: Int,
    val shortWindowCount: Int,
    val longTermCount: Int,
)

internal fun recycleBinSummaryModel(itemCount: Int, shortWindowCount: Int): RecycleBinSummaryModel {
    val total = itemCount.coerceAtLeast(0)
    val shortWindow = shortWindowCount.coerceIn(0, total)
    return RecycleBinSummaryModel(
        totalCount = total,
        shortWindowCount = shortWindow,
        longTermCount = total - shortWindow,
    )
}

@Composable
fun RecycleBinScreen(
    viewModel: RecycleBinViewModel,
    onBack: () -> Unit,
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    var group by rememberSaveable { mutableStateOf(RecycleGroup.All) }
    var pendingRestore by remember { mutableStateOf<RecycleBinItem?>(null) }

    LaunchedEffect(Unit) { viewModel.refresh() }

    pendingRestore?.let { item ->
        RestoreRecycleBinItemDialog(
            item = item,
            onConfirm = {
                viewModel.restore(item)
                pendingRestore = null
            },
            onDismiss = { pendingRestore = null },
        )
    }

    AppSecondaryScrollableContent(
        chrome = AppSecondaryPageChrome(
            role = AppPageRole.Ledger,
            title = stringResource(R.string.recycle_bin_page_title),
            subtitle = stringResource(R.string.recycle_bin_page_subtitle),
            backText = stringResource(R.string.transactions_library_back_to_library),
            onBack = onBack,
            verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
        ),
        refresh = AppSecondaryRefreshState(
            isRefreshing = state.loading && state.items.isNotEmpty(),
            onRefresh = viewModel::refresh,
        ),
    ) {
        recycleBinPageContent(
            state = state,
            onRefresh = viewModel::refresh,
            onRestore = { pendingRestore = it },
            group = group,
            onGroupChange = { group = it },
        )
    }
}

private fun LazyListScope.recycleBinPageContent(
    state: RecycleBinUiState,
    onRefresh: () -> Unit,
    onRestore: (RecycleBinItem) -> Unit,
    group: RecycleGroup,
    onGroupChange: (RecycleGroup) -> Unit,
) {
    val bodyState = recycleBinBodyState(state)
    if (!state.canModify) {
        item {
            AppDataAuthorityStrip(
                title = stringResource(R.string.recycle_bin_readonly_title),
                body = stringResource(R.string.recycle_bin_readonly_body),
                tone = DataAuthorityTone.ReadOnly,
            )
        }
    }
    if (state.message != null && bodyState != RecycleBinBodyState.LoadFailed) {
        item { AppStatusBanner(message = state.message, tone = state.messageTone) }
    }
    item {
        FlowRow(horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            RecycleGroup.entries.forEach { option ->
                AppFilterChip(stringResource(option.label), group == option, { onGroupChange(option) })
            }
        }
    }
    when (bodyState) {
        RecycleBinBodyState.LoadFailed -> item {
            AppErrorState(
                title = stringResource(R.string.recycle_bin_load_failed_title),
                body = stringResource(R.string.recycle_bin_load_failed_body),
                onRetry = onRefresh,
            )
        }
        RecycleBinBodyState.Loading -> item { RecycleBinStateCard() }
        RecycleBinBodyState.Empty -> item { RecycleBinEmptyState() }
        RecycleBinBodyState.Content -> {
            val visible = state.items.filter { group == RecycleGroup.All ||
                (it.kind in planKinds) == (group == RecycleGroup.Plans) }
            if (visible.isEmpty()) {
                item { Text(stringResource(R.string.recycle_bin_group_empty),
                    color = MaterialTheme.colorScheme.onSurfaceVariant) }
            }
            item {
                RecycleBinListCard(
                    state = state,
                    items = visible,
                    onRestore = onRestore,
                )
            }
        }
    }
    item { RecycleBinHelp(state) }
}

@Composable
private fun RecycleBinEmptyState() {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = AppSpacing.cardGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Icon(
            imageVector = Icons.Filled.RestoreFromTrash,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.size(AppSpacing.controlMinHeight),
        )
        Text(
            text = stringResource(R.string.recycle_bin_empty_title),
            style = MaterialTheme.typography.titleSmall,
            fontWeight = AppTextHierarchy.heading.weight,
            textAlign = TextAlign.Center,
        )
        Text(
            text = stringResource(R.string.recycle_bin_empty_body),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodyMedium,
            textAlign = TextAlign.Center,
        )
    }
}

@Composable
private fun RecycleBinStateCard() {
    AppContentCard {
        AppListStateContent(
            state = AppListStateSpec(
                isEmpty = true,
                loading = true,
                emptyText = stringResource(R.string.recycle_bin_empty_body),
                emptyTitle = stringResource(R.string.recycle_bin_empty_title),
                emptyBody = stringResource(R.string.recycle_bin_empty_body),
            ),
        ) {
        }
    }
}

@Composable
private fun RecycleBinListCard(
    state: RecycleBinUiState,
    items: List<RecycleBinItem>,
    onRestore: (RecycleBinItem) -> Unit,
) {
    Column {
        items.forEachIndexed { index, item ->
            AppListRow(showDivider = index < items.lastIndex) {
                if (state.canModify) {
                    AppAdaptiveContentActionRow(
                        style = AppAdaptiveContentActionStyle(compactAction = true),
                        content = { RecycleBinItemContent(item) },
                        action = { modifier ->
                            val restoreLabel = stringResource(R.string.recycle_bin_restore_named, item.title)
                            RecycleBinRestoreButton(state.busyItemKey == item.busyKey(), { onRestore(item) },
                                modifier.semantics { contentDescription = restoreLabel })
                        },
                    )
                } else RecycleBinItemContent(item)
            }
        }
    }
}

@Composable
private fun RecycleBinItemContent(item: RecycleBinItem) {
    Row(verticalAlignment = Alignment.Top) {
        val visuals = LocalThemeVisuals.current
        SettingsEntryIcon(ImageVector.vectorResource(when (item.kind) {
            "category_preference" -> R.drawable.ic_lucide_shapes
            "merchant_catalog", "merchant_alias" -> R.drawable.ic_lucide_store
            "tag_mutation" -> R.drawable.ic_lucide_tag
            "category_rule" -> R.drawable.ic_lucide_wand_sparkles
            else -> R.drawable.ic_lucide_calendar_check
        }), background = when (item.kind) {
            "goal", "category_preference" -> visuals.surfaceApricot
            "tag_mutation" -> visuals.surfaceLilac
            else -> MaterialTheme.colorScheme.primaryContainer
        })
        Spacer(Modifier.width(AppSpacing.compactGap))
        Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
            Text(item.title, style = MaterialTheme.typography.titleMedium,
                fontWeight = AppTextHierarchy.heading.weight)
            Text(item.detail, style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(stringResource(if (item.kind in planKinds) R.string.recycle_bin_archived_status
                else R.string.recycle_bin_removed_status, item.kindLabel, item.retentionLabel),
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(displayTime(item.removedAt), style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }

}

@Composable
private fun RecycleBinRestoreButton(
    busy: Boolean,
    onRestore: () -> Unit,
    modifier: Modifier,
) {
    TextButton(
        onClick = onRestore,
        enabled = !busy,
        modifier = modifier.heightIn(min = AppSpacing.controlMinHeight),
        contentPadding = PaddingValues(
            horizontal = AppSpacing.compactGap,
            vertical = AppSpacing.none,
        ),
    ) {
        Text(
            if (busy) {
                stringResource(R.string.recycle_bin_restore_busy)
            } else {
                stringResource(R.string.recycle_bin_restore)
            },
        )
    }
}

@Composable
private fun RecycleBinHelp(state: RecycleBinUiState) {
    var expanded by rememberSaveable { mutableStateOf(false) }
    val bodyState = recycleBinBodyState(state)
    val summary = recycleBinSummaryModel(state.items.size, state.shortWindowCount)
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap)) {
        AppListRow(showDivider = false) {
            SettingsEntryIcon(ImageVector.vectorResource(R.drawable.ic_lucide_info))
            Spacer(Modifier.width(AppSpacing.compactGap))
            Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
                Text(stringResource(R.string.recycle_bin_review_title), style = MaterialTheme.typography.titleSmall)
                Text(stringResource(R.string.recycle_bin_review_body), style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        if (bodyState == RecycleBinBodyState.Loading || bodyState == RecycleBinBodyState.LoadFailed) return@Column
        AppListRow(onClick = { expanded = !expanded }, showDivider = false) {
            SettingsEntryIcon(ImageVector.vectorResource(R.drawable.ic_lucide_info))
            Spacer(Modifier.width(AppSpacing.compactGap))
            Column {
                Text(stringResource(R.string.recycle_bin_retention_title), style = MaterialTheme.typography.titleSmall)
                Text(stringResource(R.string.recycle_bin_summary_line, summary.totalCount,
                    summary.shortWindowCount, summary.longTermCount),
                    style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        if (expanded) Text(stringResource(R.string.recycle_bin_retention_body),
            style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun RestoreRecycleBinItemDialog(
    item: RecycleBinItem,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.recycle_bin_restore_dialog_title)) },
        text = { Text(stringResource(R.string.recycle_bin_restore_dialog_text, item.title)) },
        confirmButton = {
            TextButton(onClick = onConfirm) {
                Text(stringResource(R.string.recycle_bin_restore_dialog_confirm))
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text(stringResource(R.string.common_cancel))
            }
        },
    )
}
