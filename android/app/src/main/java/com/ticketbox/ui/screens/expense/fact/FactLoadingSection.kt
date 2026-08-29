package com.ticketbox.ui.screens.expense.fact

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.SkeletonBlock
import com.ticketbox.ui.design.AppSpacing

/**
 * A1 首载骨架（expense==null 且 Loading）：成熟产品的占位形态，不是空白屏。
 * 与事实页正文结构同构（金额位 + 两行状态 + 若干事实行 + 卡段落）。
 */
@Composable
internal fun FactLoadingSkeleton() {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        SkeletonBlock(modifier = Modifier.fillMaxWidth(0.5f).height(AppSpacing.sectionGap))
        SkeletonBlock(modifier = Modifier.fillMaxWidth(0.3f).height(AppSpacing.cardPadding))
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            repeat(5) {
                SkeletonBlock(modifier = Modifier.fillMaxWidth().height(AppSpacing.cardPadding))
            }
        }
        SkeletonBlock(modifier = Modifier.fillMaxWidth().height(AppSpacing.controlMinHeight))
        SkeletonBlock(modifier = Modifier.fillMaxWidth().height(AppSpacing.sectionGap * 3))
        SkeletonBlock(modifier = Modifier.fillMaxWidth().height(AppSpacing.sectionGap * 3))
    }
}

/**
 * 首载失败（expense==null 且 Failed）：明确错误 + 重试，不冒充空态。
 */
@Composable
internal fun FactLoadFailedSection(
    message: String?,
    onRetry: () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        Text(
            text = stringResource(R.string.expense_fact_load_failed_title),
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.titleMedium,
        )
        Text(
            text = message ?: stringResource(R.string.expense_edit_loading_empty_fallback),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodyMedium,
        )
        AppPrimaryButton(
            text = stringResource(R.string.expense_fact_retry),
            icon = androidx.compose.material.icons.Icons.Filled.Refresh,
            onClick = onRetry,
        )
    }
}

/**
 * 已知内容 + 权威刷新失败：低层级 stale 提示（一行 meta，不抢任务焦点）。
 */
@Composable
internal fun FactStaleBanner(onRetry: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = stringResource(R.string.expense_fact_stale_banner),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
        TextButton(onClick = onRetry) {
            Text(text = stringResource(R.string.expense_fact_retry))
        }
    }
}
