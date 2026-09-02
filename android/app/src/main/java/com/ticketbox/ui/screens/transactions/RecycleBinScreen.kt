package com.ticketbox.ui.screens.transactions

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
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
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.domain.model.RecycleBinItem
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

    val bodyState = recycleBinBodyState(state)
    val subtitle = if (bodyState == RecycleBinBodyState.Content) {
        val summary = recycleBinSummaryModel(state.items.size, state.shortWindowCount)
        stringResource(
            R.string.recycle_bin_summary_line,
            summary.totalCount,
            summary.shortWindowCount,
            summary.longTermCount,
        )
    } else {
        stringResource(R.string.recycle_bin_page_subtitle)
    }

    AppSecondaryScrollableContent(
        chrome = AppSecondaryPageChrome(
            role = AppPageRole.Ledger,
            title = stringResource(R.string.recycle_bin_page_title),
            subtitle = subtitle,
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
        )
    }
}

private fun LazyListScope.recycleBinPageContent(
    state: RecycleBinUiState,
    onRefresh: () -> Unit,
    onRestore: (RecycleBinItem) -> Unit,
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
            item {
                RecycleBinListCard(
                    state = state,
                    onRestore = onRestore,
                )
            }
        }
    }
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
    onRestore: (RecycleBinItem) -> Unit,
) {
    AppContentCard(
        contentPadding = PaddingValues(horizontal = AppSpacing.cardPaddingSmall),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.none),
    ) {
        state.items.forEachIndexed { index, item ->
            AppListRow(showDivider = index < state.items.lastIndex) {
                RecycleBinRow(
                    item = item,
                    canModify = state.canModify,
                    busy = state.busyItemKey == item.busyKey(),
                    onRestore = onRestore,
                )
            }
        }
    }
}

@Composable
private fun RowScope.RecycleBinRow(
    item: RecycleBinItem,
    canModify: Boolean,
    busy: Boolean,
    onRestore: (RecycleBinItem) -> Unit,
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
        Spacer(modifier = Modifier.width(AppSpacing.smallGap))
        RecycleBinRestoreButton(
            busy = busy,
            onRestore = { onRestore(item) },
        )
    }
}

@Composable
private fun RecycleBinRestoreButton(
    busy: Boolean,
    onRestore: () -> Unit,
) {
    TextButton(
        onClick = onRestore,
        enabled = !busy,
        modifier = Modifier.heightIn(min = AppSpacing.controlMinHeight),
        contentPadding = PaddingValues(
            horizontal = AppSpacing.compactGap,
            vertical = AppSpacing.none,
        ),
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
