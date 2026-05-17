package com.ticketbox.ui.screens.ledger

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.components.formatAmount
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.viewmodel.LedgerUiState

@Composable
internal fun LedgerHeader(
    state: LedgerUiState,
    onManualAdd: () -> Unit,
) {
    val summary = state.summary
    val monthLabel = summary.monthFilter.takeIf { it.isNotBlank() }?.let(::displayMonthLabel) ?: "全部月份"
    val statusText = when {
        summary.syncing -> "更新中"
        summary.lastSyncAt != null -> "已更新 ${ledgerSyncClock(summary.lastSyncAt)}"
        else -> "本机账本可用"
    }
    PaperLedgerPanel {
        Column(
            modifier = Modifier.padding(
                horizontal = AppSpacing.cardPaddingSmall,
                vertical = AppSpacing.cardPaddingTight,
            ),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(
                    modifier = Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
                ) {
                    Text(
                        text = "纸本账本",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.labelMedium,
                        fontWeight = AppTextHierarchy.body.weight,
                    )
                    Text(
                        text = "账本",
                        style = MaterialTheme.typography.titleLarge,
                        color = MaterialTheme.colorScheme.onSurface,
                        fontWeight = AppTextHierarchy.heading.weight,
                        maxLines = 1,
                    )
                }
                LedgerStatusPill(text = statusText, active = summary.syncing)
            }
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
            ) {
                LedgerKpiCell(
                    label = "$monthLabel 合计",
                    value = formatAmount(summary.totalAmountCents),
                    modifier = Modifier.weight(1.45f),
                    emphasized = true,
                )
                LedgerKpiCell(
                    label = "账单",
                    value = "${summary.itemCount} 笔",
                    modifier = Modifier.weight(1f),
                )
            }
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = "已确认支出 · 可离线查看",
                    modifier = Modifier.weight(1f),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                if (!state.readOnly) {
                    Button(
                        modifier = Modifier.heightIn(min = AppSpacing.controlMinHeight),
                        onClick = onManualAdd,
                        contentPadding = PaddingValues(horizontal = AppSpacing.cardPaddingTight, vertical = 0.dp),
                        colors = ButtonDefaults.buttonColors(
                            containerColor = MaterialTheme.colorScheme.primary,
                            contentColor = MaterialTheme.colorScheme.onPrimary,
                        ),
                    ) {
                        Icon(Icons.Filled.Add, contentDescription = null, modifier = Modifier.size(17.dp))
                        Spacer(Modifier.width(AppSpacing.miniGap + AppSpacing.tinyGap))
                        Text("记一笔")
                    }
                }
            }
        }
    }
}

@Composable
private fun PaperLedgerPanel(content: @Composable () -> Unit) {
    val visuals = LocalThemeVisuals.current
    val shape = RoundedCornerShape(AppRadius.medium)
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .clip(shape)
            .background(MaterialTheme.colorScheme.surface.copy(alpha = 0.98f))
            .drawBehind {
                drawRect(
                    color = visuals.primary.copy(alpha = 0.42f),
                    size = Size(width = AppSpacing.miniGap.toPx(), height = size.height),
                )
            }
            .border(
                BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.54f)),
                shape,
            ),
    ) {
        Box(modifier = Modifier.padding(start = AppSpacing.miniGap)) {
            content()
        }
    }
}

@Composable
private fun LedgerKpiCell(
    label: String,
    value: String,
    modifier: Modifier = Modifier,
    emphasized: Boolean = false,
) {
    Column(
        modifier = modifier
            .clip(RoundedCornerShape(AppRadius.small))
            .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.36f))
            .padding(horizontal = AppSpacing.compactGap, vertical = AppSpacing.contentGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        Text(
            text = label,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Text(
            text = value,
            color = if (emphasized) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface,
            style = if (emphasized) MaterialTheme.typography.titleLarge else MaterialTheme.typography.titleMedium,
            fontWeight = AppTextHierarchy.heading.weight,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun LedgerStatusPill(text: String, active: Boolean) {
    val visuals = LocalThemeVisuals.current
    Row(
        modifier = Modifier
            .clip(RoundedCornerShape(AppRadius.pill))
            .background(
                if (active) {
                    visuals.primary.copy(alpha = 0.14f)
                } else {
                    MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.58f)
                },
            )
            .padding(horizontal = AppSpacing.contentGap, vertical = AppSpacing.smallGap),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.miniGap + AppSpacing.tinyGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            imageVector = Icons.Filled.Sync,
            contentDescription = null,
            tint = if (active) visuals.primary else MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.size(14.dp),
        )
        Text(
            text = text,
            color = if (active) visuals.primary else MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall,
            fontWeight = AppTextHierarchy.body.weight,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}
