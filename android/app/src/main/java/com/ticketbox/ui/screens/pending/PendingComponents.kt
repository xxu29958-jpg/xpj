package com.ticketbox.ui.screens.pending

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AddPhotoAlternate
import androidx.compose.material.icons.filled.Info
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.components.AppContentCard
import com.ticketbox.ui.components.AppPageHeader
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.PrimaryCtaButton
import com.ticketbox.ui.components.SafeBadge
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy

@Composable
internal fun PendingMessageCard(message: String) {
    AppContentCard {
        Row(
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                modifier = Modifier
                    .size(32.dp),
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
            )
        }
    }
}

/**
 * 待确认页头。
 *
 * 紧凑型重设计（v0.11，对去重 audit）：
 * - 单一页头 [AppPageHeader] —— 不再额外渲染 [PendingHeader] 的"待处理"section title
 * - hero 数字 [pendingCount] 和重复计数集中到一个 KPI 行，不再重复 3 次
 * - 上传 CTA 仍然显眼；"识别内容只作为草稿"提示去掉（subtitle 已经在说"确认后才进入账本"）
 * - 显示模式（紧凑/舒适）由 [trailingAction] 注入到 AppPageHeader 的 action 槽，与 SafeBadge 并列
 *
 * @param trailingAction 头部右上角附加按钮——通常是显示模式切换。SafeBadge 始终展示。
 */
@Composable
internal fun PendingTop(
    pendingCount: Int,
    duplicateCount: Int,
    uploading: Boolean,
    readOnly: Boolean,
    onUploadScreenshot: () -> Unit,
    trailingAction: (@Composable () -> Unit)? = null,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap)) {
        AppPageHeader(
            title = "待确认",
            subtitle = if (pendingCount > 0) {
                "$pendingCount 张截图待核对，确认后才进入账本"
            } else {
                "还没有待核对截图，上传后会先放在这里"
            },
        ) {
            trailingAction?.invoke()
            SafeBadge()
        }

        // KPI 行：左 hero 主计数 + 右辅助计数。原来用 AppContentCard 包了一层，
        // hero 数字和 subtitle 里的 pendingCount 重复展示——这里把卡片和重复说明都拆掉，
        // 只留一行清楚的 metric。如果未来需要更多维度（最近确认率等），再补 card。
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.cardPaddingSmall),
            verticalAlignment = Alignment.Bottom,
        ) {
            Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(
                    text = pendingCount.toString(),
                    color = MaterialTheme.colorScheme.onSurface,
                    style = MaterialTheme.typography.headlineLarge,
                    fontWeight = AppTextHierarchy.hero.weight,
                    maxLines = 1,
                )
                Text(
                    text = "张待核对",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.labelMedium,
                    fontWeight = AppTextHierarchy.caption.weight,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            if (duplicateCount > 0) {
                Column(
                    horizontalAlignment = Alignment.End,
                    verticalArrangement = Arrangement.spacedBy(2.dp),
                ) {
                    Text(
                        text = duplicateCount.toString(),
                        color = MaterialTheme.colorScheme.primary,
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = AppTextHierarchy.heading.weight,
                    )
                    Text(
                        text = "疑似重复",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.labelSmall,
                        fontWeight = AppTextHierarchy.caption.weight,
                    )
                }
            }
        }

        PrimaryCtaButton(
            modifier = Modifier.fillMaxWidth(),
            enabled = !uploading && !readOnly,
            icon = Icons.Filled.AddPhotoAlternate,
            text = when {
                readOnly -> "只读角色不能上传"
                uploading -> "正在上传截图"
                else -> "上传截图"
            },
            onClick = onUploadScreenshot,
        )
    }
}

/**
 * 显示模式（紧凑/舒适）切换按钮 —— 由 [PendingScreen] 注入到 [PendingTop] 的 trailing 槽。
 * 之前作为独立的 [PendingHeader] 一整行存在，跟 PendingTop 的 AppPageHeader 内容重叠。
 */
@Composable
internal fun PendingDisplayModeButton(
    loading: Boolean,
    displayMode: PendingDisplayMode,
    onClick: () -> Unit,
) {
    AppSecondaryButton(
        text = if (loading) "刷新中" else pendingDisplayModeLabel(displayMode),
        enabled = !loading,
        onClick = onClick,
    )
}
