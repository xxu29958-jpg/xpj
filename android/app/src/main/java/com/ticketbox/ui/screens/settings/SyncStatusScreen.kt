package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CloudDone
import androidx.compose.material.icons.filled.CloudUpload
import androidx.compose.material.icons.filled.ErrorOutline
import androidx.compose.material.icons.filled.RestartAlt
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material.icons.filled.SyncProblem
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.OutboxStatus
import com.ticketbox.ui.components.AppOutlinedButton
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSolidCard
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.StateTone
import com.ticketbox.viewmodel.OutboxStatusViewModel

/**
 * ADR-0038 PR-2g.11: the offline-sync surface — the user-facing half
 * of the outbox. One focal status card (calm states, never an alarm
 * for plain "queued"), then only the rows that need a decision:
 * CONFLICT (keep mine / drop mine) and FAILED (retry / drop).
 */
@Composable
fun SyncStatusScreen(
    viewModel: OutboxStatusViewModel,
    onBack: () -> Unit,
) {
    val state by viewModel.uiState.collectAsState()
    val status = state.status

    SettingsPageFrame(
        title = "离线同步",
        subtitle = "联网后会自动把离线改动同步到服务器；有冲突或失败时在这里处理。",
        onBack = onBack,
    ) {
        SyncSummaryCard(status)

        state.message?.let { msg ->
            Text(
                text = msg,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        if (status.conflicts.isNotEmpty()) {
            SettingsSection(title = "需要你确认", icon = Icons.Filled.SyncProblem) {
                status.conflicts.forEach { row ->
                    ConflictCard(
                        row = row,
                        busy = state.busyRowId == row.id,
                        onKeepMine = { viewModel.keepMine(row) },
                        onDropMine = { viewModel.dropMine(row) },
                    )
                }
            }
        }

        if (status.failed.isNotEmpty()) {
            SettingsSection(title = "同步失败", icon = Icons.Filled.ErrorOutline) {
                status.failed.forEach { row ->
                    FailedCard(
                        row = row,
                        busy = state.busyRowId == row.id,
                        onRetry = { viewModel.retry(row) },
                        onDrop = { viewModel.dropFailed(row) },
                    )
                }
            }
        }
    }
}

@Composable
private fun SyncSummaryCard(status: OutboxStatus) {
    val tokens = LocalStateTokens.current
    val tone: StateTone
    val icon: ImageVector
    val title: String
    val body: String
    when {
        status.needsUserAction -> {
            tone = tokens.danger
            icon = Icons.Filled.SyncProblem
            val pending = status.conflicts.size + status.failed.size
            title = "$pending 笔需要你处理"
            body = "下面的改动没能自动同步，需要你决定怎么办。"
        }
        status.queueDepth > 0 -> {
            tone = tokens.info
            icon = Icons.Filled.Sync
            title = "${status.queueDepth} 笔待同步"
            body = "联网后会自动上传，不用你操作。"
        }
        else -> {
            tone = tokens.success
            icon = Icons.Filled.CloudDone
            title = "全部已同步"
            body = "离线改动都已安全送达服务器。"
        }
    }

    AppSolidCard {
        Row(
            modifier = Modifier.fillMaxWidth().padding(AppSpacing.cardPadding),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                modifier = Modifier.size(44.dp).clip(CircleShape).background(tone.bg),
                contentAlignment = Alignment.Center,
            ) {
                Icon(icon, contentDescription = null, tint = tone.fg, modifier = Modifier.size(22.dp))
            }
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
            ) {
                Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                Text(
                    body,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
private fun ConflictCard(
    row: OutboxRow,
    busy: Boolean,
    onKeepMine: () -> Unit,
    onDropMine: () -> Unit,
) {
    // Only the expense family can re-fetch a fresh token for "keep
    // mine" in v1; other families are drop-only here.
    val canKeep = row.targetId.startsWith("expense:")
    AppSolidCard {
        Column(
            modifier = Modifier.fillMaxWidth().padding(AppSpacing.cardPadding),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        ) {
            Text(
                text = "离线时：${mutationLabel(row.type)}",
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                text = row.lastError?.takeIf { it.isNotBlank() }
                    ?: "这条改动已在其它设备被改动，没能自动同步。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
            ) {
                if (canKeep) {
                    AppPrimaryButton(
                        text = "用我的覆盖",
                        icon = Icons.Filled.CloudUpload,
                        modifier = Modifier.weight(1f),
                        enabled = !busy,
                        onClick = onKeepMine,
                    )
                }
                AppOutlinedButton(
                    onClick = onDropMine,
                    modifier = Modifier.weight(1f),
                    enabled = !busy,
                    danger = true,
                ) {
                    Text("放弃我的改动")
                }
            }
        }
    }
}

@Composable
private fun FailedCard(
    row: OutboxRow,
    busy: Boolean,
    onRetry: () -> Unit,
    onDrop: () -> Unit,
) {
    AppSolidCard {
        Column(
            modifier = Modifier.fillMaxWidth().padding(AppSpacing.cardPadding),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        ) {
            Text(
                text = "离线时：${mutationLabel(row.type)}",
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                text = row.lastError?.takeIf { it.isNotBlank() } ?: "这条改动没能同步成功。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
            ) {
                AppPrimaryButton(
                    text = "重试",
                    icon = Icons.Filled.RestartAlt,
                    modifier = Modifier.weight(1f),
                    enabled = !busy,
                    onClick = onRetry,
                )
                AppOutlinedButton(
                    onClick = onDrop,
                    modifier = Modifier.weight(1f),
                    enabled = !busy,
                    danger = true,
                ) {
                    Text("放弃")
                }
            }
        }
    }
}

private fun mutationLabel(type: PendingMutationType): String = when (type) {
    PendingMutationType.PatchExpense -> "修改账单"
    PendingMutationType.ConfirmExpense -> "确认入账"
    PendingMutationType.RejectExpense -> "删除账单"
    PendingMutationType.MarkNotDuplicate -> "保留账单（非重复）"
    PendingMutationType.RetryOcr -> "重新识别"
    PendingMutationType.RecognizeText -> "识别文字"
    PendingMutationType.ReplaceItems -> "修改小票明细"
    PendingMutationType.ReplaceSplits -> "修改家庭拆账"
    PendingMutationType.AcknowledgeItemsMismatch -> "确认小票差异"
    PendingMutationType.ConfirmedBatchUpdate -> "批量修改已确认账单"
    PendingMutationType.UpdateCategoryRule -> "修改分类规则"
    PendingMutationType.DeleteCategoryRule -> "删除分类规则"
    PendingMutationType.UpdateMerchantAlias -> "修改商家别名"
    PendingMutationType.DeleteMerchantAlias -> "删除商家别名"
    PendingMutationType.UpdateGoal -> "修改目标"
    PendingMutationType.UpdateIncomePlan -> "修改收入计划"
    PendingMutationType.Unknown -> "改动"
}
