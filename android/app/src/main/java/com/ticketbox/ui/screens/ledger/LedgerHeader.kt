package com.ticketbox.ui.screens.ledger

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.R
import com.ticketbox.ui.components.formatAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalCurrencyCode
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.viewmodel.LedgerUiState

/**
 * W2-B 流水头部：删除与导航壳重复的「流水」标题，金额成为唯一视觉重心
 * （tabular 墨色大数字回答「当前可见列表合计多少」），笔数与新鲜度降为
 * 伴生行。合计只表达 server-owned signed streamAmountCents 的可见合计。
 */
@Composable
internal fun LedgerHeader(
    state: LedgerUiState,
) {
    val summary = state.summary
    val statusText = ledgerHeaderStatusText(state, ledgerSyncEvidence(state))
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
        Row(
            verticalAlignment = Alignment.Bottom,
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        ) {
            Text(
                text = formatAmount(summary.totalAmountCents, LocalCurrencyCode.current),
                color = MaterialTheme.colorScheme.onSurface,
                style = MaterialTheme.typography.headlineMedium.copy(
                    fontWeight = FontWeight.SemiBold,
                ).tabularNum(),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = stringResource(R.string.ledger_header_count_value, summary.itemCount),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.labelMedium.tabularNum(),
                modifier = Modifier.padding(bottom = AppSpacing.tinyGap),
                maxLines = 1,
            )
        }
        Text(
            text = statusText,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
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
