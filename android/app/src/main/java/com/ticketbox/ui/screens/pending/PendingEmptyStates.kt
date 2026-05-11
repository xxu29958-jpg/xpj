package com.ticketbox.ui.screens.pending

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Info
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.components.AppEmptyStateCard
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.AppSectionHeader
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.ReceiptIllustration
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalThemeVisuals

@Composable
internal fun UploadFlowCard() {
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
internal fun UploadProgressCard() {
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
    val visuals = LocalThemeVisuals.current
    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(5.dp),
    ) {
        Box(
            modifier = Modifier
                .size(38.dp)
                .clip(RoundedCornerShape(13.dp))
                .background(visuals.chipSelected),
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
internal fun LoadingPendingState() {
    val visuals = LocalThemeVisuals.current
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
                        .background(visuals.chipSelected.copy(alpha = 0.72f)),
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
internal fun EmptyPendingState(
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
                    Text("2. 选择\u201C上传到小票夹\u201D快捷指令。")
                    Text("3. 上传成功后回到这里刷新。")
                }
            }
        }
    }
}
