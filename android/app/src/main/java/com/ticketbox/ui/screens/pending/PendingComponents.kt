package com.ticketbox.ui.screens.pending

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AddPhotoAlternate
import androidx.compose.material.icons.filled.Info
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.AppHeroCard
import com.ticketbox.ui.components.AppPageHeader
import com.ticketbox.ui.components.PrimaryCtaButton
import com.ticketbox.ui.components.SafeBadge
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.LocalThemeVisuals

@Composable
internal fun PendingMessageCard(message: String) {
    val visuals = LocalThemeVisuals.current
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
                    .background(visuals.chipSelected.copy(alpha = 0.82f)),
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
internal fun PendingTop(
    pendingCount: Int,
    duplicateCount: Int,
    uploading: Boolean,
    onUploadScreenshot: () -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
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
                modifier = Modifier.padding(horizontal = 18.dp, vertical = 14.dp),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(
                    modifier = Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    Text(
                        text = "等待你确认",
                        color = MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.82f),
                        style = MaterialTheme.typography.labelLarge,
                    )
                    Text(
                        text = "$pendingCount 张",
                        color = MaterialTheme.colorScheme.onPrimary,
                        style = MaterialTheme.typography.headlineMedium,
                        fontWeight = FontWeight.Black,
                    )
                    Text(
                        text = "识别结果只是草稿",
                        color = MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.78f),
                        style = MaterialTheme.typography.bodySmall,
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
                        modifier = Modifier.weight(0.92f),
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
            .padding(horizontal = 8.dp, vertical = 8.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(2.dp),
    ) {
        Text(
            text = value,
            color = MaterialTheme.colorScheme.primary,
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.Black,
        )
        Text(
            text = label,
            color = MaterialTheme.colorScheme.primary.copy(alpha = 0.55f),
            style = MaterialTheme.typography.labelSmall,
        )
    }
}
