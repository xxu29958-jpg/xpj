package com.ticketbox.ui.screens

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.AppPageHeader
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppScrollableContent
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.ReceivablesUiState
import com.ticketbox.viewmodel.ReceivablesViewModel

/**
 * ADR-0049 P3b / ⑤c (slice ⑤c-2) 欠我的(应收) —— [com.ticketbox.ui.navigation.ReceivablesRoute] 内的
 * **只读发现面**。家人接受你发起的拆账后，你作为跨账本债权人的应收都汇总在这里。每行复用 [MemberDebtRow]
 * （communal 关系行：债务人名 + 「我帮你垫的…」关系主句 + open 时细进度条 + neutral/success 徽章永不红），
 * **静态不可点**（不传 onClick）——镜像 web ⑤c-3 的 `.dt-card--static`：还款由债务人在手机 App 发起、债权人
 * 确认，§7.0 命名要对上的人但不催。镜像 [DebtListScreen] 的生活流骨架（[AppScrollableContent] +
 * [AppPageHeader] + [AppStatusBanner]）；overlay 自带 [BackHandler]
 * （[[project_overlay_screen_needs_own_backhandler]]）。
 */
@Composable
fun ReceivablesScreen(
    viewModel: ReceivablesViewModel,
    onBack: () -> Unit,
) {
    val state by viewModel.state.collectAsState()

    BackHandler(onBack = onBack)

    AppScrollableContent(
        role = AppPageRole.Stats,
        isRefreshing = state.isLoading,
        onRefresh = viewModel::refresh,
        hasBottomBar = false,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
    ) {
        item { ReceivablesHeader(onBack = onBack) }
        state.error?.let { err ->
            item { AppStatusBanner(message = err, tone = MessageTone.Danger) }
        }
        receivablesSection(state = state)
    }
}

@Composable
private fun ReceivablesHeader(onBack: () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        TextButton(onClick = onBack) {
            Icon(
                Icons.AutoMirrored.Filled.ArrowBack,
                contentDescription = stringResource(R.string.debt_list_topbar_back),
                modifier = Modifier.size(18.dp),
            )
            Spacer(Modifier.width(4.dp))
            Text(stringResource(R.string.debt_list_topbar_back))
        }
        AppPageHeader(
            title = stringResource(R.string.receivables_topbar_title),
            subtitle = stringResource(R.string.receivables_intro_body),
        )
    }
}

private fun LazyListScope.receivablesSection(state: ReceivablesUiState) {
    if (state.receivables.isEmpty() && !state.isLoading) {
        item { ReceivablesEmptyStateCard() }
        return
    }
    // 全部是 member 应收(viewer_is_debtor=false → creditor 侧「我帮你垫的」)，静态不可点（只读发现面，
    // 还款由债务人在手机 App 发起、债权人确认）。外币成员应收同样走 communal 行（无金额英雄，不受 FX 影响）。
    items(state.receivables, key = { it.publicId }) { debt ->
        MemberDebtRow(debt = debt)
    }
}

@Composable
private fun ReceivablesEmptyStateCard() {
    AppGlassCard(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.fillMaxWidth().padding(AppSpacing.sectionGap),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(
                stringResource(R.string.receivables_empty_title),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
            )
            Spacer(Modifier.size(AppSpacing.smallGap))
            Text(
                stringResource(R.string.receivables_empty_body),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}
