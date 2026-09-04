package com.ticketbox.ui.screens.ledger

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.ui.components.AppAmountText
import com.ticketbox.ui.components.formatAmount
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalCurrencyCode
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.viewmodel.LedgerUiState

private object LedgerHeaderLayout {
    val ClipNotchHeight = 36.dp
}

/**
 * W2-B 流水头部：删除与导航壳重复的「流水」标题，金额成为唯一视觉重心
 * （tabular 墨色大数字回答「当前可见列表合计多少」），笔数与新鲜度降为
 * 伴生行。合计只表达 server-owned signed streamAmountCents 的可见合计。
 *
 * visual-ledger 批：金额迁 [AppAmountRole.Hero]（金额单源阶梯 34sp +
 * autosize），系统大字号 / 长合法金额自动收敛、不再截断丢数字；笔数与
 * 新鲜度合并为一条可换行伴生 meta，不再与金额抢同一行。票头右缘加
 * coral 票面夹刻（纯品牌装饰，对应 Web 票带右缘的 --brand-clip 刻条）。
 */
@Composable
internal fun LedgerHeader(
    state: LedgerUiState,
) {
    val summary = state.summary
    val statusText = ledgerHeaderStatusText(state, ledgerSyncEvidence(state))
    Box(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = AppSpacing.miniGap),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
        ) {
            // 口径提示：过滤后可见列表的 server stream 合计，不是账户支出/净资产。
            Text(
                text = stringResource(R.string.ledger_header_total_current_list),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.labelSmall,
                maxLines = 1,
            )
            AppAmountText(
                text = formatAmount(summary.totalAmountCents, LocalCurrencyCode.current),
                modifier = Modifier.fillMaxWidth(),
                role = AppAmountRole.Hero,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                text = stringResource(R.string.ledger_header_count_value, summary.itemCount) +
                    " · " + statusText,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.labelSmall.tabularNum(),
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
        }
        // 票面夹刻：票头右缘上段的一小段 coral 刻条，纯品牌装饰、无交互。
        Box(
            modifier = Modifier
                .align(Alignment.TopEnd)
                .padding(top = AppSpacing.smallGap)
                .width(3.dp)
                .height(LedgerHeaderLayout.ClipNotchHeight)
                .clip(RoundedCornerShape(topStart = 2.dp, bottomStart = 2.dp))
                .background(LocalThemeVisuals.current.clipCoral),
        )
    }
}

@Composable
private fun ledgerHeaderStatusText(
    state: LedgerUiState,
    evidence: LedgerSyncEvidence,
): String = when (evidence) {
    LedgerSyncEvidence.Refreshing -> stringResource(R.string.ledger_header_status_syncing)
    LedgerSyncEvidence.BackendSynced -> state.lastSyncAt?.let {
        stringResource(R.string.ledger_header_status_synced, ledgerSyncClock(it))
    } ?: stringResource(R.string.components_data_authority_backend_title)
    LedgerSyncEvidence.LocalCache -> stringResource(R.string.ledger_header_status_offline)
}
