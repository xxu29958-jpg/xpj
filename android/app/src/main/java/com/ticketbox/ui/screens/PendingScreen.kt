package com.ticketbox.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ReceiptLong
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.Expense
import com.ticketbox.ui.components.ExpenseCard
import com.ticketbox.ui.components.ExpensePreviewMode
import com.ticketbox.ui.components.RefreshableLazyColumn
import com.ticketbox.viewmodel.PendingUiState

private enum class PendingDisplayMode {
    Compact,
    Comfortable,
}

@Composable
fun PendingScreen(
    state: PendingUiState,
    onRefresh: () -> Unit,
    onEdit: (Expense) -> Unit,
    onConfirm: (Expense) -> Unit,
    onReject: (Expense) -> Unit,
    onKeepDuplicate: (Expense) -> Unit,
) {
    var showUploadGuide by remember { mutableStateOf(false) }
    var displayMode by rememberSaveable { mutableStateOf(PendingDisplayMode.Compact) }

    RefreshableLazyColumn(
        isRefreshing = state.loading,
        onRefresh = onRefresh,
    ) {
        state.message?.let { message ->
            item {
                Text(
                    text = message,
                    color = MaterialTheme.colorScheme.secondary,
                )
            }
        }

        when {
            state.items.isEmpty() && state.loading -> {
                item { LoadingPendingState() }
            }

            state.items.isEmpty() -> {
                item {
                    EmptyPendingState(
                        showUploadGuide = showUploadGuide,
                        onToggleGuide = { showUploadGuide = !showUploadGuide },
                        onRefresh = onRefresh,
                    )
                }
            }

            else -> {
                item {
                    PendingHeader(
                        loading = state.loading,
                        displayMode = displayMode,
                        onDisplayModeChange = { displayMode = it },
                        onRefresh = onRefresh,
                    )
                }
            }
        }

        if (state.items.isNotEmpty()) {
            items(state.items, key = { it.id }) { expense ->
                ExpenseCard(
                    expense = expense,
                    thumbnail = state.thumbnails[expense.id],
                    previewMode = when (displayMode) {
                        PendingDisplayMode.Compact -> ExpensePreviewMode.Compact
                        PendingDisplayMode.Comfortable -> ExpensePreviewMode.Comfortable
                    },
                    showActions = true,
                    actionsEnabled = expense.id !in state.actionInProgressIds,
                    onEdit = { onEdit(expense) },
                    onConfirm = { onConfirm(expense) },
                    onReject = { onReject(expense) },
                    onKeepDuplicate = { onKeepDuplicate(expense) },
                )
            }
        }
    }
}

@Composable
private fun LoadingPendingState() {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.72f),
        ),
    ) {
        Text(
            text = "正在加载待确认账单…",
            modifier = Modifier.padding(18.dp),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun PendingHeader(
    loading: Boolean,
    displayMode: PendingDisplayMode,
    onDisplayModeChange: (PendingDisplayMode) -> Unit,
    onRefresh: () -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
                Text("待确认", style = MaterialTheme.typography.headlineSmall)
                Text(
                    text = "下拉刷新，确认后才会进入账本。",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            OutlinedButton(
                enabled = !loading,
                onClick = onRefresh,
            ) {
                Text(if (loading) "刷新中" else "刷新")
            }
        }

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            FilterChip(
                selected = displayMode == PendingDisplayMode.Compact,
                onClick = { onDisplayModeChange(PendingDisplayMode.Compact) },
                label = { Text("紧凑") },
            )
            FilterChip(
                selected = displayMode == PendingDisplayMode.Comfortable,
                onClick = { onDisplayModeChange(PendingDisplayMode.Comfortable) },
                label = { Text("舒适") },
            )
        }
    }
}

@Composable
private fun EmptyPendingState(
    showUploadGuide: Boolean,
    onToggleGuide: () -> Unit,
    onRefresh: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Card(
            modifier = Modifier.fillMaxWidth(),
            colors = CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.72f),
            ),
        ) {
            Column(
                modifier = Modifier.padding(18.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                ReceiptEmptyIllustration()
                Spacer(Modifier.height(2.dp))
                Text("还没有待确认账单", style = MaterialTheme.typography.titleLarge)
                Text(
                    text = "在 iPhone 上分享账单截图到“小票夹”，上传成功后会出现在这里，确认后才会入账。",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Button(
                    modifier = Modifier.fillMaxWidth(),
                    onClick = onToggleGuide,
                ) {
                    Text(if (showUploadGuide) "收起上传方法" else "查看上传方法")
                }
                OutlinedButton(
                    modifier = Modifier.fillMaxWidth(),
                    onClick = onRefresh,
                ) {
                    Text("刷新看看")
                }
            }
        }
        if (showUploadGuide) {
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.62f),
                ),
            ) {
                Column(
                    modifier = Modifier.padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text("上传方法", style = MaterialTheme.typography.titleMedium)
                    Text("1. 在 iPhone 上打开账单截图。")
                    Text("2. 点分享，选择“上传到小票夹”快捷指令。")
                    Text("3. 上传成功后回到这里刷新。")
                }
            }
        }
    }
}

@Composable
private fun ReceiptEmptyIllustration() {
    Box(
        modifier = Modifier
            .size(92.dp)
            .clip(CircleShape)
            .background(MaterialTheme.colorScheme.primary.copy(alpha = 0.16f)),
        contentAlignment = Alignment.Center,
    ) {
        Box(
            modifier = Modifier
                .size(64.dp)
                .clip(RoundedCornerShape(22.dp))
                .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.62f)),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                imageVector = Icons.AutoMirrored.Filled.ReceiptLong,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(36.dp),
            )
        }
    }
}
