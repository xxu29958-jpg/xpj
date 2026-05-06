package com.ticketbox.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AddPhotoAlternate
import androidx.compose.material.icons.filled.Info
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.Expense
import com.ticketbox.ui.components.AppEmptyStateCard
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.AppHeroCard
import com.ticketbox.ui.components.AppPageHeader
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppScrollableContent
import com.ticketbox.ui.components.AppSectionHeader
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.ExpenseCard
import com.ticketbox.ui.components.ExpensePreviewMode
import com.ticketbox.ui.components.PrimaryCtaButton
import com.ticketbox.ui.components.ReceiptIllustration
import com.ticketbox.ui.components.SafeBadge
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
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
    var wasLoading by remember { mutableStateOf(state.loading) }
    val listState = rememberLazyListState()
    val duplicateCount = state.items.count { it.duplicateStatus == "suspected" }

    LaunchedEffect(state.loading) {
        if (wasLoading && !state.loading) {
            listState.scrollToItem(0)
        }
        wasLoading = state.loading
    }

    AppScrollableContent(
        role = AppPageRole.Pending,
        isRefreshing = state.loading,
        onRefresh = onRefresh,
        listState = listState,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
    ) {
        item {
            PendingTop(
                pendingCount = state.items.size,
                duplicateCount = duplicateCount,
                uploading = state.uploading,
                onUploadScreenshot = onUploadScreenshot,
            )
        }

        if (state.items.isEmpty()) {
            item { UploadFlowCard() }
        }

        state.message?.let { message ->
            item {
                PendingMessageCard(message = message)
            }
        }

        if (state.uploading) {
            item { UploadProgressCard() }
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
private fun PendingMessageCard(message: String) {
    AppGlassCard(containerAlpha = 0.94f) {
        Row(
            modifier = Modifier.padding(horizontal = 15.dp, vertical = 13.dp),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                modifier = Modifier
                    .size(34.dp)
                    .clip(RoundedCornerShape(12.dp))
                    .background(MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.82f)),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    imageVector = Icons.Filled.Info,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.size(18.dp),
                )
            }
            Text(
                text = message,
                modifier = Modifier.weight(1f),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.Medium,
            )
        }
    }
}

@Composable
private fun PendingTop(
    pendingCount: Int,
    duplicateCount: Int,
    uploading: Boolean,
    onUploadScreenshot: () -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap)) {
        AppPageHeader(
            title = if (pendingCount > 0) {
                "今天有 $pendingCount 张截图待确认"
            } else {
                "今天还没有截图待确认"
            },
            subtitle = "不会自动入账，确认后才进入账本",
        ) {
            SafeBadge()
        }

        AppHeroCard {
            Row(
                modifier = Modifier.padding(horizontal = AppSpacing.cardPadding, vertical = 18.dp),
                horizontalArrangement = Arrangement.spacedBy(14.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(
                    modifier = Modifier.weight(0.92f),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Text(
                        text = "等待你确认",
                        color = MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.82f),
                        style = MaterialTheme.typography.titleSmall,
                    )
                    Text(
                        text = "$pendingCount 张",
                        color = MaterialTheme.colorScheme.onPrimary,
                        style = MaterialTheme.typography.headlineLarge,
                        fontWeight = FontWeight.Black,
                    )
                    Text(
                        text = "识别结果只是草稿",
                        color = MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.78f),
                        style = MaterialTheme.typography.bodyMedium,
                    )
                }
                if (pendingCount == 0 && duplicateCount == 0) {
                    Box(
                        modifier = Modifier.weight(0.82f),
                        contentAlignment = Alignment.CenterEnd,
                    ) {
                        PendingHeroStatusPill()
                    }
                } else {
                    Row(
                        modifier = Modifier.weight(0.98f),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        PendingHeroMetric("$pendingCount", "待确认", modifier = Modifier.weight(1f))
                        PendingHeroMetric("$duplicateCount", "疑似重复", modifier = Modifier.weight(1f))
                    }
                }
            }
        }

        PrimaryCtaButton(
            modifier = Modifier.fillMaxWidth(),
            enabled = !uploading,
            icon = Icons.Filled.AddPhotoAlternate,
            text = if (uploading) "正在上传截图" else "上传截图",
            onClick = onUploadScreenshot,
        )
    }
}

@Composable
private fun PendingHeroStatusPill() {
    Column(
        modifier = Modifier
            .clip(RoundedCornerShape(AppRadius.medium))
            .background(Color.White.copy(alpha = 0.18f))
            .border(
                width = 1.dp,
                color = Color.White.copy(alpha = 0.24f),
                shape = RoundedCornerShape(AppRadius.medium),
            )
            .padding(horizontal = 14.dp, vertical = 12.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Text(
            text = "今日状态",
            color = MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.72f),
            style = MaterialTheme.typography.labelSmall,
            fontWeight = FontWeight.Bold,
        )
        Text(
            text = "无待确认",
            color = MaterialTheme.colorScheme.onPrimary,
            style = MaterialTheme.typography.labelLarge,
            fontWeight = FontWeight.Black,
        )
    }
}

@Composable
private fun PendingHeroMetric(value: String, label: String, modifier: Modifier = Modifier) {
    Column(
        modifier = modifier
            .clip(RoundedCornerShape(AppRadius.medium))
            .background(Color.White.copy(alpha = 0.88f))
            .border(
                width = 1.dp,
                color = Color.White.copy(alpha = 0.46f),
                shape = RoundedCornerShape(AppRadius.medium),
            )
            .padding(horizontal = 8.dp, vertical = 10.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(3.dp),
    ) {
        Text(
            text = value,
            color = MaterialTheme.colorScheme.primary,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Black,
        )
        Text(
            text = label,
            color = MaterialTheme.colorScheme.primary.copy(alpha = 0.55f),
            style = MaterialTheme.typography.labelSmall,
        )
    }
}

@Composable
private fun UploadFlowCard() {
    AppGlassCard(containerAlpha = 0.92f) {
        Row(
            modifier = Modifier.padding(horizontal = 14.dp, vertical = 12.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            FlowStep("1", "上传", "选一张截图", modifier = Modifier.weight(1f))
            Text("→", color = MaterialTheme.colorScheme.onSurfaceVariant)
            FlowStep("2", "核对", "补金额商家", modifier = Modifier.weight(1f))
            Text("→", color = MaterialTheme.colorScheme.onSurfaceVariant)
            FlowStep("3", "入账", "确认后记录", modifier = Modifier.weight(1f))
        }
    }
}

@Composable
private fun UploadProgressCard() {
    AppGlassCard(containerAlpha = 0.96f) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text(
                text = "正在创建待确认账单",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Black,
            )
            Text(
                text = "上传完成后会自动刷新，不会直接入账。",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
            LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
        }
    }
}

@Composable
private fun FlowStep(
    number: String,
    title: String,
    subtitle: String,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(5.dp),
    ) {
        Box(
            modifier = Modifier
                .size(38.dp)
                .clip(RoundedCornerShape(13.dp))
                .background(MaterialTheme.colorScheme.primaryContainer),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                text = number,
                color = MaterialTheme.colorScheme.primary,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Black,
            )
        }
        Text(title, style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.Black, maxLines = 1)
        Text(subtitle, color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.labelSmall, maxLines = 1)
    }
}

@Composable
private fun LoadingPendingState() {
    AppGlassCard(containerAlpha = 0.94f) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(11.dp),
        ) {
            Row(
                horizontalArrangement = Arrangement.spacedBy(12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(
                    modifier = Modifier
                        .size(42.dp)
                        .clip(RoundedCornerShape(14.dp))
                        .background(MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.72f)),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        imageVector = Icons.Filled.Info,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.size(19.dp),
                    )
                }
                Column(
                    modifier = Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(3.dp),
                ) {
                    Text(
                        text = "正在整理待确认账单",
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.Black,
                    )
                    Text(
                        text = "截图上传后会出现在这里，确认后才会入账。",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }
            LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
        }
    }
}

@Composable
private fun PendingHeader(
    loading: Boolean,
    displayMode: PendingDisplayMode,
    onDisplayModeChange: (PendingDisplayMode) -> Unit,
    onRefresh: () -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            AppSectionHeader(
                title = "待处理",
                subtitle = "点进截图后补金额、商家和分类",
                modifier = Modifier.weight(1f),
            )
            AppSecondaryButton(
                text = if (loading) "刷新中" else "刷新",
                enabled = !loading,
                onClick = onRefresh,
            )
        }
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            AppFilterChip(
                selected = displayMode == PendingDisplayMode.Compact,
                onClick = { onDisplayModeChange(PendingDisplayMode.Compact) },
                label = "紧凑",
            )
            AppFilterChip(
                selected = displayMode == PendingDisplayMode.Comfortable,
                onClick = { onDisplayModeChange(PendingDisplayMode.Comfortable) },
                label = "舒适",
            )
        }
    }
}

@Composable
private fun EmptyPendingState(
    uploading: Boolean,
    showUploadGuide: Boolean,
    onToggleGuide: () -> Unit,
    onRefresh: () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        AppSectionHeader(
            title = "待处理",
            subtitle = "上传截图后，会出现在这里等你确认",
        )
        AppEmptyStateCard {
            Row(
                modifier = Modifier.padding(AppSpacing.cardPadding),
                horizontalArrangement = Arrangement.spacedBy(16.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                ReceiptIllustration(compact = true)
                Column(
                    modifier = Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Text("还没有待确认账单", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Black)
                    Text(
                        text = "截图上传后不会自动入账，你确认后才会记录。",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            AppSecondaryButton(
                text = if (showUploadGuide) "收起 iPhone 方法" else "iPhone 快捷指令",
                modifier = Modifier.weight(1.25f),
                leadingIcon = Icons.Filled.Info,
                onClick = onToggleGuide,
            )
            AppSecondaryButton(
                text = "刷新",
                modifier = Modifier.weight(0.75f),
                enabled = !uploading,
                onClick = onRefresh,
            )
        }
        if (showUploadGuide) {
            AppGlassCard(containerAlpha = 0.94f) {
                Column(
                    modifier = Modifier.padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text("iPhone 上传方法", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Black)
                    Text("1. 打开账单截图，点分享。")
                    Text("2. 选择“上传到小票夹”快捷指令。")
                    Text("3. 上传成功后回到这里刷新。")
                }
            }
        }
    }
}
