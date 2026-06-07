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
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.Expense
import com.ticketbox.ui.components.AppContentCard
import com.ticketbox.ui.components.AppPageHeader
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.PrimaryCtaButton
import com.ticketbox.ui.components.SafeBadge
import com.ticketbox.ui.components.formatExpensePrimaryAmount
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
            title = stringResource(R.string.pending_top_title),
            subtitle = if (pendingCount > 0) {
                stringResource(R.string.pending_top_subtitle_has_items, pendingCount)
            } else {
                stringResource(R.string.pending_top_subtitle_empty)
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
                    text = stringResource(R.string.pending_top_metric_caption),
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
                        text = stringResource(R.string.pending_top_duplicate_caption),
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
                readOnly -> stringResource(R.string.pending_top_cta_readonly)
                uploading -> stringResource(R.string.pending_top_cta_uploading)
                else -> stringResource(R.string.pending_top_cta_upload)
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
        text = if (loading) stringResource(R.string.pending_display_mode_button_loading) else pendingDisplayModeLabel(displayMode),
        enabled = !loading,
        onClick = onClick,
    )
}

/**
 * ADR-0038 撤销 snackbar — 删除账单后短暂内可点 [onUndo] 恢复。
 *
 * **两个独立计时器、各管各的**:
 * - VM 拥有 5s "banner 显示窗口" ([PendingViewModel.startUndoTimer]),只
 *   决定**什么时候把 banner 收起来**。Compose 生命周期(LazyColumn dispose
 *   / tab 切换 / NavHost pop)不影响它。
 * - Server 拥有 5min "retention 窗口",真正的**可撤销边界**。banner 没
 *   了之后(VM 5s 烧完),server 端可能还能撤——但 UI 不再露这条路。banner
 *   还在的时候点撤销,server 也可能返 404(被另一端撤了 / 被回收了 / 几
 *   分钟前的 banner 但 retention 已过)。
 *
 * 所以这个按钮的**实际可点性**始终以 server 响应为准:VM 不预判"5s 内
 * 一定能撤",只决定 banner 显示多久。VM 5s 之内点击会发请求,server 说成
 * 功就成功,server 说 404 就走 [PendingViewModel.undoReject] 的失败分支。
 *
 * [expense] 用来在 banner 里**标识被删的具体账单** (商家 / 金额),解决
 * 在线 Synced(A) 删完 banner 还在时离线 Queued reject(B) 的歧义场景:
 * 没标识用户会以为撤销的是最近一次操作 (B),实际撤销的是 A。
 *
 * 和 merchant_alias `MerchantAliasesScreen` 的撤销 bar 同 pattern, /web 的
 * 5s CSS undo-banner 也对齐——三端"删除即可撤销 5s"做同一种 UX。
 */
@Composable
internal fun PendingUndoRejectBanner(
    expense: Expense,
    onUndo: () -> Unit,
) {
    val merchant = expense.merchant?.trim()?.takeIf { it.isNotEmpty() }
    val amount = expense.amountCents?.let { formatExpensePrimaryAmount(expense) }
    val descriptor = listOfNotNull(merchant, amount).joinToString(" · ")
    val label = if (descriptor.isNotEmpty()) {
        stringResource(R.string.pending_undo_banner_label_with_descriptor, descriptor)
    } else {
        stringResource(R.string.pending_undo_banner_label)
    }
    AppContentCard {
        Row(
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                imageVector = Icons.Filled.Info,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(20.dp),
            )
            Text(
                text = label,
                modifier = Modifier.weight(1f),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodyMedium,
            )
            AppSecondaryButton(text = stringResource(R.string.pending_undo_banner_action), onClick = onUndo)
        }
    }
}
