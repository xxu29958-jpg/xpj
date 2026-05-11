package com.ticketbox.ui.screens.pending

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppSectionHeader
import com.ticketbox.ui.components.AppSecondaryButton

internal enum class PendingDisplayMode {
    Compact,
    Comfortable,
}

internal fun pendingDisplayModeLabel(displayMode: PendingDisplayMode): String {
    return when (displayMode) {
        PendingDisplayMode.Compact -> "紧凑"
        PendingDisplayMode.Comfortable -> "舒适"
    }
}

@Composable
internal fun PendingHeader(
    loading: Boolean,
    displayMode: PendingDisplayMode,
    onOpenTools: () -> Unit,
) {
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
            text = if (loading) "刷新中" else pendingDisplayModeLabel(displayMode),
            enabled = !loading,
            onClick = onOpenTools,
        )
    }
}

@Composable
internal fun PendingToolsSheet(
    loading: Boolean,
    displayMode: PendingDisplayMode,
    onDisplayModeChange: (PendingDisplayMode) -> Unit,
    onRefresh: () -> Unit,
    onDismiss: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 18.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(
                text = "待处理设置",
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.Black,
            )
            Text(
                text = "调整列表密度，或重新整理待确认截图。",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
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
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            AppSecondaryButton(
                text = if (loading) "刷新中" else "刷新待确认",
                modifier = Modifier.weight(1f),
                enabled = !loading,
                onClick = onRefresh,
            )
            Button(
                modifier = Modifier.weight(1f),
                onClick = onDismiss,
            ) {
                Text("完成")
            }
        }
    }
}
