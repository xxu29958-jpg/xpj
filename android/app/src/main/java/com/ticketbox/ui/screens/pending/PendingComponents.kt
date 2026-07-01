package com.ticketbox.ui.screens.pending

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
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
import com.ticketbox.R
import com.ticketbox.domain.model.Expense
import com.ticketbox.ui.components.AppPageHeader
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.PrimaryCtaButton
import com.ticketbox.ui.components.formatExpensePrimaryAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy

@Composable
internal fun PendingMessageCard(message: String) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = AppSpacing.smallGap),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            imageVector = Icons.Filled.Info,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary,
            modifier = Modifier.size(AppSpacing.cardPadding),
        )
        Text(
            text = message,
            modifier = Modifier.weight(1f),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodyMedium,
        )
    }
}

@Composable
internal fun PendingTop(
    counts: PendingQueueCounts,
    uploading: Boolean,
    readOnly: Boolean,
    onUploadScreenshot: () -> Unit,
    trailingAction: (@Composable () -> Unit)? = null,
) {
    val pendingCount = counts.all
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap)) {
        AppPageHeader(
            title = stringResource(R.string.pending_top_title),
            subtitle = when {
                pendingCount > 0 -> stringResource(R.string.pending_top_subtitle_has_items)
                readOnly -> stringResource(R.string.pending_top_subtitle_empty_readonly)
                else -> stringResource(R.string.pending_top_subtitle_empty)
            },
        ) {
            trailingAction?.invoke()
        }

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.cardPaddingSmall),
            verticalAlignment = Alignment.Bottom,
        ) {
            Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
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
            if (counts.readyToConfirm > 0 || counts.needsAmount > 0 || counts.duplicate > 0) {
                Column(
                    horizontalAlignment = Alignment.End,
                    verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
                ) {
                    PendingTopMetric(
                        visible = counts.readyToConfirm > 0,
                        value = counts.readyToConfirm,
                        label = stringResource(R.string.pending_filter_label_ready_to_confirm),
                    )
                    PendingTopMetric(
                        visible = counts.needsAmount > 0,
                        value = counts.needsAmount,
                        label = stringResource(R.string.pending_filter_label_needs_amount),
                    )
                    PendingTopMetric(
                        visible = counts.duplicate > 0,
                        value = counts.duplicate,
                        label = stringResource(R.string.pending_top_duplicate_caption),
                    )
                }
            }
        }

        if (!readOnly) {
            PrimaryCtaButton(
                modifier = Modifier.fillMaxWidth(),
                enabled = !uploading,
                icon = Icons.Filled.AddPhotoAlternate,
                text = if (uploading) {
                    stringResource(R.string.pending_top_cta_uploading)
                } else {
                    stringResource(R.string.pending_top_cta_upload)
                },
                onClick = onUploadScreenshot,
            )
        }
    }
}

@Composable
private fun PendingTopMetric(
    visible: Boolean,
    value: Int,
    label: String,
) {
    if (!visible) return
    Row(
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = value.toString(),
            color = MaterialTheme.colorScheme.primary,
            style = MaterialTheme.typography.titleSmall,
            fontWeight = AppTextHierarchy.heading.weight,
            maxLines = 1,
        )
        Text(
            text = label,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall,
            fontWeight = AppTextHierarchy.caption.weight,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
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
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = AppSpacing.smallGap),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            imageVector = Icons.Filled.Info,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary,
            modifier = Modifier.size(AppSpacing.cardPadding),
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
