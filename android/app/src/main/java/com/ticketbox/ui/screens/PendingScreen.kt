package com.ticketbox.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ReceiptLong
import androidx.compose.material.icons.filled.AddPhotoAlternate
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
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
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.components.RefreshableLazyColumn
import com.ticketbox.ui.components.ScreenHeader
import com.ticketbox.ui.components.SoftPanel
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
    onUploadScreenshot: () -> Unit,
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
                        uploading = state.uploading,
                        showUploadGuide = showUploadGuide,
                        onToggleGuide = { showUploadGuide = !showUploadGuide },
                        onUploadScreenshot = onUploadScreenshot,
                        onRefresh = onRefresh,
                    )
                }
            }

            else -> {
                item {
                    PendingHeader(
                        loading = state.loading,
                        uploading = state.uploading,
                        displayMode = displayMode,
                        onDisplayModeChange = { displayMode = it },
                        onUploadScreenshot = onUploadScreenshot,
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
    SoftPanel {
        Text(
            text = "正在整理待确认账单...",
            modifier = Modifier.padding(16.dp),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun PendingHeader(
    loading: Boolean,
    uploading: Boolean,
    displayMode: PendingDisplayMode,
    onDisplayModeChange: (PendingDisplayMode) -> Unit,
    onUploadScreenshot: () -> Unit,
    onRefresh: () -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        ScreenHeader(
            title = "待确认账单",
            subtitle = "截图先变成草稿，确认后才入账。",
        ) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                QuietOutlinedButton(
                    text = if (loading) "刷新中" else "刷新",
                    enabled = !loading,
                    onClick = onRefresh,
                )
                Button(
                    enabled = !uploading,
                    onClick = onUploadScreenshot,
                ) {
                    Icon(Icons.Filled.AddPhotoAlternate, contentDescription = null, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(6.dp))
                    Text(if (uploading) "上传中" else "上传")
                }
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
    uploading: Boolean,
    showUploadGuide: Boolean,
    onToggleGuide: () -> Unit,
    onUploadScreenshot: () -> Unit,
    onRefresh: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 2.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        ScreenHeader(
            title = "待确认账单",
            subtitle = "0 笔待处理，上传截图后会出现在这里。",
        ) {
            Button(
                enabled = !uploading,
                onClick = onUploadScreenshot,
            ) {
                Icon(Icons.Filled.AddPhotoAlternate, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(6.dp))
                Text(if (uploading) "上传中" else "上传")
            }
        }
        SoftPanel {
            Row(
                modifier = Modifier.padding(14.dp),
                horizontalArrangement = Arrangement.spacedBy(12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                ReceiptEmptyIllustration()
                Column(
                    modifier = Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Text("还没有待确认账单", style = MaterialTheme.typography.titleMedium)
                    Text(
                        text = "识别结果只是草稿，确认后才会入账。",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            QuietOutlinedButton(
                text = if (showUploadGuide) "收起 iPhone 方法" else "iPhone 快捷指令",
                modifier = Modifier.weight(1f),
                onClick = onToggleGuide,
            )
            QuietOutlinedButton(
                text = "刷新",
                modifier = Modifier.weight(1f),
                enabled = !uploading,
                onClick = onRefresh,
            )
        }
        if (showUploadGuide) {
            SoftPanel(containerAlpha = 0.52f) {
                Column(
                    modifier = Modifier.padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text("iPhone 上传方法", style = MaterialTheme.typography.titleMedium)
                    Text("1. 打开账单截图，点分享。")
                    Text("2. 选择“上传到小票夹”快捷指令。")
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
            .size(68.dp)
            .clip(CircleShape)
            .background(MaterialTheme.colorScheme.primary.copy(alpha = 0.16f)),
        contentAlignment = Alignment.Center,
    ) {
        Box(
            modifier = Modifier
                .size(48.dp)
                .clip(RoundedCornerShape(16.dp))
                .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.62f)),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                imageVector = Icons.AutoMirrored.Filled.ReceiptLong,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(28.dp),
            )
        }
    }
}
