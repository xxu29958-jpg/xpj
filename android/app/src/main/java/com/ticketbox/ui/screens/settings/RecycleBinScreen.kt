package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.RestoreFromTrash
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.RecycleBinItem
import com.ticketbox.ui.components.AppOutlinedButton
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.ListItemSkeleton
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.viewmodel.RecycleBinUiState
import com.ticketbox.viewmodel.RecycleBinViewModel
import com.ticketbox.viewmodel.busyKey
import com.valentinilk.shimmer.shimmer

@Composable
fun RecycleBinScreen(
    viewModel: RecycleBinViewModel,
    onBack: () -> Unit,
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
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

    SettingsPageFrame(
        title = stringResource(R.string.recycle_bin_page_title),
        subtitle = stringResource(R.string.recycle_bin_page_subtitle),
        onBack = onBack,
        status = {
            AppStatusBanner(
                message = state.message,
                tone = if (state.loadFailed) MessageTone.Danger else MessageTone.Neutral,
            )
        },
    ) {
        RecycleBinListSection(
            state = state,
            onRefresh = viewModel::refresh,
            onRestore = { pendingRestore = it },
        )
    }
}

@Composable
private fun RecycleBinListSection(
    state: RecycleBinUiState,
    onRefresh: () -> Unit,
    onRestore: (RecycleBinItem) -> Unit,
) {
    SettingsSection(
        title = stringResource(R.string.recycle_bin_section_items),
        icon = Icons.Filled.DeleteOutline,
    ) {
        RecycleBinOverview(state)
        if (!state.canModify) {
            RecycleBinInlineState(
                title = stringResource(R.string.recycle_bin_readonly_title),
                body = stringResource(R.string.recycle_bin_readonly_body),
                icon = Icons.Filled.Lock,
            )
        }
        RecycleBinRows(state = state, onRestore = onRestore)
        QuietOutlinedButton(
            text = if (state.loading) {
                stringResource(R.string.recycle_bin_refresh_loading)
            } else {
                stringResource(R.string.recycle_bin_refresh)
            },
            leadingIcon = Icons.Filled.Refresh,
            onClick = onRefresh,
            enabled = !state.loading && state.busyItemKey == null,
            modifier = Modifier.fillMaxWidth(),
        )
    }
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
private fun RecycleBinOverview(state: RecycleBinUiState) {
    val summary = recycleBinSummaryModel(state.items.size, state.shortWindowCount)
    SettingsOpenPanel(
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        ) {
            RecycleBinMetric(
                label = stringResource(R.string.recycle_bin_summary_total_label),
                value = summary.totalCount,
                modifier = Modifier.weight(1f),
            )
            RecycleBinMetric(
                label = stringResource(R.string.recycle_bin_summary_limited_label),
                value = summary.shortWindowCount,
                modifier = Modifier.weight(1f),
            )
            RecycleBinMetric(
                label = stringResource(R.string.recycle_bin_summary_long_label),
                value = summary.longTermCount,
                modifier = Modifier.weight(1f),
            )
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.medium))
    }
}

@Composable
private fun RecycleBinMetric(
    label: String,
    value: Int,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
    ) {
        Text(
            text = stringResource(R.string.recycle_bin_summary_count, value),
            style = MaterialTheme.typography.titleLarge,
            fontWeight = AppTextHierarchy.heading.weight,
            maxLines = 1,
        )
        Text(
            text = label,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall,
            maxLines = 1,
        )
    }
}

@Composable
private fun RecycleBinRows(
    state: RecycleBinUiState,
    onRestore: (RecycleBinItem) -> Unit,
) {
    if (state.items.isEmpty() && state.loading) {
        Column(modifier = Modifier.shimmer()) {
            repeat(3) { ListItemSkeleton(horizontalPadding = 0.dp) }
        }
        return
    }
    if (state.items.isEmpty() && state.loadFailed) {
        RecycleBinInlineState(
            title = stringResource(R.string.recycle_bin_load_failed_title),
            body = stringResource(R.string.recycle_bin_load_failed_body),
            icon = Icons.Filled.Refresh,
        )
        return
    }
    if (state.items.isEmpty()) {
        RecycleBinInlineState(
            title = stringResource(R.string.recycle_bin_empty_title),
            body = stringResource(R.string.recycle_bin_empty_body),
            icon = Icons.Filled.DeleteOutline,
        )
        return
    }
    SettingsOpenPanel(verticalArrangement = Arrangement.spacedBy(0.dp)) {
        state.items.forEachIndexed { index, item ->
            if (index > 0) {
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.medium))
            }
            RecycleBinRow(
                item = item,
                canModify = state.canModify,
                busy = state.busyItemKey == item.busyKey(),
                onRestore = onRestore,
            )
        }
    }
}

@Composable
private fun RecycleBinInlineState(
    title: String,
    body: String,
    icon: androidx.compose.ui.graphics.vector.ImageVector,
) {
    SettingsOpenPanel(
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
            verticalAlignment = Alignment.Top,
        ) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
            )
            Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
                Text(
                    text = title,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = AppTextHierarchy.heading.weight,
                )
                Text(
                    text = body,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        }
    }
}

@Composable
private fun RecycleBinRow(
    item: RecycleBinItem,
    canModify: Boolean,
    busy: Boolean,
    onRestore: (RecycleBinItem) -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = AppSpacing.smallGap),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = item.title,
                    modifier = Modifier.weight(1f),
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = AppTextHierarchy.body.weight,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    text = item.kindLabel,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.primary,
                    maxLines = 1,
                )
            }
            Text(
                text = item.detail,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = stringResource(
                    R.string.recycle_bin_row_status,
                    item.retentionLabel,
                    displayTime(item.removedAt),
                ),
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        if (canModify) {
            RecycleBinRestoreButton(
                busy = busy,
                onRestore = { onRestore(item) },
            )
        }
    }
}

@Composable
private fun RecycleBinRestoreButton(
    busy: Boolean,
    onRestore: () -> Unit,
) {
    AppOutlinedButton(
        onClick = onRestore,
        enabled = !busy,
        modifier = Modifier.heightIn(min = AppSpacing.controlMinHeight),
        contentPadding = PaddingValues(horizontal = AppSpacing.compactGap, vertical = 0.dp),
    ) {
        Icon(
            imageVector = Icons.Filled.RestoreFromTrash,
            contentDescription = null,
        )
        Spacer(modifier = Modifier.width(AppSpacing.tinyGap))
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
