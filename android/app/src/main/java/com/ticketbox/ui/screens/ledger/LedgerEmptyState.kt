package com.ticketbox.ui.screens.ledger

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.automirrored.filled.ReceiptLong
import androidx.compose.material.icons.Icons
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.components.AppEmptyStateCard
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.viewmodel.LedgerUiState

@Composable
internal fun EmptyLedgerState(
    state: LedgerUiState,
    onClearFilters: () -> Unit,
    onSync: () -> Unit,
    onManualAdd: () -> Unit,
) {
    val hasMonth = state.monthFilter.isNotBlank()
    val hasCategory = state.categoryFilter.isNotBlank()
    val hasActiveFilters = hasMonth || hasCategory || state.query.isNotBlank()
    val title = when {
        hasMonth && hasCategory -> "${displayMonthLabel(state.monthFilter)} 暂无 ${state.categoryFilter} 分类账单"
        hasMonth -> "${displayMonthLabel(state.monthFilter)} 暂无已确认账单"
        hasCategory -> "暂无 ${state.categoryFilter} 分类账单"
        else -> "本地还没有已确认账单"
    }
    val body = if (hasMonth || hasCategory) {
        "可以切换月份、选择全部分类，或先更新账本。"
    } else {
        "在待确认页确认几笔账单后，账本会在这里显示。"
    }

    AppEmptyStateCard {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            LedgerEmptyIllustration()
            Text(title, style = MaterialTheme.typography.titleMedium)
            Text(
                text = body,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Text(
                text = ledgerFilterSummary(state),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                if (hasActiveFilters) {
                    Button(
                        modifier = Modifier.weight(1f),
                        onClick = onClearFilters,
                    ) {
                        Text("重置筛选")
                    }
                    QuietOutlinedButton(
                        text = "更新账本",
                        modifier = Modifier.weight(1f),
                        enabled = !state.syncing,
                        onClick = onSync,
                    )
                } else {
                    Button(
                        modifier = Modifier.weight(1f),
                        onClick = onManualAdd,
                    ) {
                        Text("手动记一笔")
                    }
                    QuietOutlinedButton(
                        text = "更新账本",
                        modifier = Modifier.weight(1f),
                        enabled = !state.syncing,
                        onClick = onSync,
                    )
                }
            }
        }
    }
}

@Composable
private fun LedgerEmptyIllustration() {
    val visuals = LocalThemeVisuals.current
    Box(
        modifier = Modifier
            .size(76.dp)
            .clip(CircleShape)
            .background(visuals.primary.copy(alpha = 0.14f)),
        contentAlignment = Alignment.Center,
    ) {
        Box(
            modifier = Modifier
                .size(52.dp)
                .clip(RoundedCornerShape(18.dp))
                .background(visuals.chipSelected.copy(alpha = 0.66f)),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                imageVector = Icons.AutoMirrored.Filled.ReceiptLong,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(30.dp),
            )
        }
    }
}
