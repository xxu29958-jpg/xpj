package com.ticketbox.ui.screens.settings.categoryrules

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.RuleApplicationBatch
import com.ticketbox.domain.model.RuleApplyConfirmedResult
import com.ticketbox.domain.model.RuleApplyPreviewItem
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy

@Composable
internal fun ConfirmedRuleApplyPanel(
    preview: RuleApplyConfirmedResult?,
    busy: Boolean,
    readOnly: Boolean,
    onPreview: () -> Unit,
    onConfirm: () -> Unit,
) {
    AppGlassCard(containerAlpha = 0.98f) {
        Column(
            modifier = Modifier.padding(AppSpacing.compactGap),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        ) {
            Text(
                text = "先预览已入账账单中可被规则更新的分类，再手动确认应用。",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            preview?.let { result ->
                ConfirmedRulePreviewSummary(result)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(
                    enabled = !busy,
                    onClick = onPreview,
                ) {
                    Text(if (busy) "处理中" else "预览")
                }
                Button(
                    enabled = !busy && !readOnly && (preview?.changedCount ?: 0) > 0,
                    onClick = onConfirm,
                ) {
                    Text("确认应用")
                }
            }
            if (readOnly) {
                Text(
                    text = "当前角色为只读，不能应用到已入账账单。",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
internal fun RuleApplicationHistory(
    applications: List<RuleApplicationBatch>,
    readOnly: Boolean,
    busy: Boolean,
    onRollback: (RuleApplicationBatch) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        if (applications.isEmpty()) {
            Text(
                text = "暂无应用记录。",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        } else {
            applications.forEach { application ->
                RuleApplicationCard(
                    application = application,
                    readOnly = readOnly,
                    busy = busy,
                    onRollback = { onRollback(application) },
                )
            }
        }
    }
}

@Composable
private fun ConfirmedRulePreviewSummary(result: RuleApplyConfirmedResult) {
    Text(
        text = "扫描 ${result.confirmedScanned} 笔 · 可更新 ${result.changedCount} 笔 · 未命中 ${result.noMatchCount} 笔",
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    if (result.scanLimitReached) {
        Text(
            text = "本次只扫描前 ${result.scanLimit} 笔。",
            color = MaterialTheme.colorScheme.secondary,
        )
    }
    result.items.take(5).forEach { item ->
        RuleApplyPreviewRow(item)
    }
}

@Composable
private fun RuleApplyPreviewRow(item: RuleApplyPreviewItem) {
    AppGlassCard(containerAlpha = 0.82f) {
        Column(
            modifier = Modifier.padding(AppSpacing.compactPadding),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
        ) {
            Text(
                text = item.merchant?.takeIf { it.isNotBlank() } ?: "未填写商家",
                style = MaterialTheme.typography.labelLarge,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = "${item.currentCategory} -> ${item.suggestedCategory} · ${item.ruleKeyword}",
                color = MaterialTheme.colorScheme.primary,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

@Composable
private fun RuleApplicationCard(
    application: RuleApplicationBatch,
    readOnly: Boolean,
    busy: Boolean,
    onRollback: () -> Unit,
) {
    AppGlassCard(containerAlpha = 0.98f) {
        Column(
            modifier = Modifier.padding(AppSpacing.compactGap),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(
                    text = if (application.isRolledBack) "已回退" else "已应用",
                    style = MaterialTheme.typography.titleSmall,
                )
                Text(
                    text = "${application.changedCount} 笔",
                    color = MaterialTheme.colorScheme.primary,
                    fontWeight = AppTextHierarchy.body.weight,
                )
            }
            Text(
                text = "扫描 ${application.pendingScanned} 笔 · ${displayTime(application.createdAt)}",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            application.rolledBackAt?.let {
                Text(
                    text = "回退时间：${displayTime(it)}",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            if (!readOnly && !application.isRolledBack) {
                OutlinedButton(
                    enabled = !busy,
                    onClick = onRollback,
                ) {
                    Text("回退")
                }
            }
        }
    }
}
