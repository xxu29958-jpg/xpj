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
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.design.AppTextHierarchy

/**
 * 待确认页的"显示密度"枚举 + 工具 sheet。
 *
 * v0.11 重构：原 [PendingHeader] composable 被合并到 [PendingTop] 的 trailingAction，
 * 不再单独渲染"待处理"section title——避免和页头 AppPageHeader 的"待确认"重复出现。
 */
internal enum class PendingDisplayMode {
    Compact,
    Comfortable,
}

@Composable
internal fun pendingDisplayModeLabel(displayMode: PendingDisplayMode): String {
    return when (displayMode) {
        PendingDisplayMode.Compact -> stringResource(R.string.pending_tools_density_compact)
        PendingDisplayMode.Comfortable -> stringResource(R.string.pending_tools_density_comfortable)
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
                text = stringResource(R.string.pending_tools_title),
                style = MaterialTheme.typography.titleLarge,
                fontWeight = AppTextHierarchy.heading.weight,
            )
            Text(
                text = stringResource(R.string.pending_tools_subtitle),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            AppFilterChip(
                selected = displayMode == PendingDisplayMode.Compact,
                onClick = { onDisplayModeChange(PendingDisplayMode.Compact) },
                label = stringResource(R.string.pending_tools_density_compact),
            )
            AppFilterChip(
                selected = displayMode == PendingDisplayMode.Comfortable,
                onClick = { onDisplayModeChange(PendingDisplayMode.Comfortable) },
                label = stringResource(R.string.pending_tools_density_comfortable),
            )
        }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            AppSecondaryButton(
                text = if (loading) {
                    stringResource(R.string.pending_tools_refresh_loading)
                } else {
                    stringResource(R.string.pending_tools_refresh)
                },
                modifier = Modifier.weight(1f),
                enabled = !loading,
                onClick = onRefresh,
            )
            Button(
                modifier = Modifier.weight(1f),
                onClick = onDismiss,
            ) {
                Text(stringResource(R.string.pending_tools_done))
            }
        }
    }
}
