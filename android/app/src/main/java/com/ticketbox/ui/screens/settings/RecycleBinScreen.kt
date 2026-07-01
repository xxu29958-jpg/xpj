package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
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
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.ListItemSkeleton
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.design.AppSpacing
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
        status = { AppStatusBanner(message = state.message, tone = MessageTone.Neutral) },
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
        SettingsOpenPanel(
            verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        ) {
                RecycleBinRows(state = state, onRestore = onRestore)
                OutlinedButton(
                    onClick = onRefresh,
                    enabled = !state.loading && state.busyItemKey == null,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(
                        if (state.loading) {
                            stringResource(R.string.recycle_bin_refresh_loading)
                        } else {
                            stringResource(R.string.recycle_bin_refresh)
                        },
                    )
                }
        }
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
    if (state.items.isEmpty()) {
        Text(
            text = stringResource(R.string.recycle_bin_empty),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        return
    }
    state.items.forEach { item ->
        RecycleBinRow(
            item = item,
            canModify = state.canModify,
            busy = state.busyItemKey == item.busyKey(),
            onRestore = onRestore,
        )
    }
}

@Composable
private fun RecycleBinRow(
    item: RecycleBinItem,
    canModify: Boolean,
    busy: Boolean,
    onRestore: (RecycleBinItem) -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap + AppSpacing.tinyGap),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                text = item.title,
                modifier = Modifier.weight(1f),
                style = MaterialTheme.typography.titleSmall,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = item.kindLabel,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.primary,
            )
        }
        Text(
            text = item.detail,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
            text = stringResource(
                R.string.recycle_bin_row_status,
                item.retentionLabel,
                displayTime(item.removedAt),
            ),
            style = MaterialTheme.typography.bodySmall,
            color = if (item.isShortWindow) {
                MaterialTheme.colorScheme.tertiary
            } else {
                MaterialTheme.colorScheme.onSurfaceVariant
            },
        )
        if (canModify) {
            OutlinedButton(
                onClick = { onRestore(item) },
                enabled = !busy,
                modifier = Modifier.fillMaxWidth(),
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
