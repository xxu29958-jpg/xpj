package com.ticketbox.ui.screens.pending.sheets

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.design.AppTextHierarchy

/**
 * BulkConfirm BottomSheet — slice 3 M5。
 *
 * 调用方负责传入「可直接确认」筛选下的统计：
 *  - readyCount：amount 完整、非 suspected 的可确认数量
 *  - missingAmountSkipCount：缺金额会被跳过的数量
 *  - duplicateSkipCount：疑似重复会被跳过、需单独二次确认的数量
 *
 * 操作：
 *  - 二次确认 → onConfirmReady() 触发 ViewModel.confirmReadyExpenses
 *  - 缺金额跳过，疑似重复跳过；任何失败不影响其他项
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun BulkConfirmSheetContent(
    readyCount: Int,
    missingAmountSkipCount: Int,
    duplicateSkipCount: Int,
    inProgress: Boolean,
    onConfirmReady: () -> Unit,
    onDismiss: () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 18.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("批量确认这一批账单", style = MaterialTheme.typography.titleLarge, fontWeight = AppTextHierarchy.heading.weight)
        Text(
            text = "会逐条确认这批账单，单条失败不影响其他。",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )

        AppGlassCard(containerAlpha = 0.94f) {
            Column(
                modifier = Modifier.padding(horizontal = 14.dp, vertical = 12.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                StatLine(label = "本次将确认", value = "$readyCount 条")
                if (missingAmountSkipCount > 0) {
                    StatLine(label = "缺金额跳过", value = "$missingAmountSkipCount 条")
                }
                if (duplicateSkipCount > 0) {
                    StatLine(label = "疑似重复跳过", value = "$duplicateSkipCount 条（请单独二次确认）")
                }
            }
        }

        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            AppSecondaryButton(
                text = "取消",
                modifier = Modifier.weight(1f),
                enabled = !inProgress,
                onClick = onDismiss,
            )
            Button(
                modifier = Modifier.weight(1.4f),
                enabled = !inProgress && readyCount > 0,
                onClick = onConfirmReady,
            ) {
                Text(if (inProgress) "确认中…" else "确认 $readyCount 条")
            }
        }
    }
}

@Composable
private fun StatLine(label: String, value: String) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(label, color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodyMedium)
        Text(value, fontWeight = AppTextHierarchy.body.weight, style = MaterialTheme.typography.bodyMedium)
    }
}
