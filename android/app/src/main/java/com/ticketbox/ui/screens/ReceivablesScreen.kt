package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.AppListStateContent
import com.ticketbox.ui.components.AppListStateMessage
import com.ticketbox.ui.components.AppListStateSpec
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryRefreshState
import com.ticketbox.ui.components.AppSecondaryScrollableContent
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.ReceivablesUiState
import com.ticketbox.viewmodel.ReceivablesViewModel

/**
 * ADR-0049 P3b / ⑤c+⑤b-2 欠我的(应收) —— [com.ticketbox.ui.navigation.ReceivablesRoute] 内的 creditor
 * 发现 + 确认面。家人接受你发起的拆账后，你作为跨账本债权人的应收都汇总在这里。每行复用 [MemberDebtRow]
 * （communal 关系行：债务人名 + 「我帮你垫的…」关系主句 + open 时细进度条 + neutral/success 徽章永不红）。
 *
 * ⑤b-2 把 ⑤c-2 的「静态不可点」反转为可点：行 tap 进跨账本 debt detail，债权人在那里确认/拒绝对方在手机
 * App 发起的还款 proposal（§5.2 participant-scoped 路径）——这是翻 `DEBT_ROLLOUT` 后 creditor 唯一的
 * Android 确认入口。导航由 [com.ticketbox.ui.navigation.ReceivablesRoute] 持有（[onOpenReceivable] 回调），
 * §7.0 命名要对上的人但不催。镜像 [DebtListScreen] 的生活流骨架（[AppScrollableContent] + [AppPageHeader]
 * + [AppStatusBanner]）；overlay 自带 [BackHandler]（[[project_overlay_screen_needs_own_backhandler]]）。
 */
@Composable
fun ReceivablesScreen(
    viewModel: ReceivablesViewModel,
    onOpenReceivable: (Debt) -> Unit,
    onBack: () -> Unit,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()

    AppSecondaryScrollableContent(
        chrome = AppSecondaryPageChrome(
            role = AppPageRole.Stats,
            title = stringResource(R.string.receivables_topbar_title),
            subtitle = stringResource(R.string.receivables_intro_body),
            backText = stringResource(R.string.debt_list_topbar_back),
            onBack = onBack,
            hasBottomBar = false,
            verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
        ),
        refresh = AppSecondaryRefreshState(
            isRefreshing = ReadableRefreshIndicator.isActive(
                loading = state.isLoading,
                hasReadableData = state.receivables.isNotEmpty(),
            ),
            onRefresh = viewModel::refresh,
        ),
    ) {
        readableListInlineError(hasRows = state.receivables.isNotEmpty(), error = state.error)?.let { err ->
            item { AppStatusBanner(message = err, tone = MessageTone.Danger) }
        }
        receivablesSection(state = state, onOpenReceivable = onOpenReceivable)
    }
}
private fun LazyListScope.receivablesSection(
    state: ReceivablesUiState,
    onOpenReceivable: (Debt) -> Unit,
) {
    val bodyState = readableListBodyState(
        hasRows = state.receivables.isNotEmpty(),
        isLoading = state.isLoading,
        error = state.error,
    )
    if (bodyState != ReadableListBodyState.Content) {
        item {
            ReceivablesListStateCard(
                loading = bodyState == ReadableListBodyState.Loading,
                error = state.error.takeIf { bodyState == ReadableListBodyState.LoadFailed },
            )
        }
        return
    }
    // 全部是 member 应收(viewer_is_debtor=false → creditor 侧「我帮你垫的」)。⑤b-2 起可点进跨账本详情确认
    // 对方的还款。外币成员应收同样走 communal 行（无金额英雄，不受 FX 影响）；点进详情后外币会退回会计卡
    // （MemberSharedThingCard 的 §2.6 防御），与同账本成员债详情一致。
    items(state.receivables, key = { it.publicId }) { debt ->
        MemberDebtRow(debt = debt, onClick = { onOpenReceivable(debt) })
    }
}

@Composable
private fun ReceivablesListStateCard(
    loading: Boolean,
    error: UiText?,
) {
    AppGlassCard(modifier = Modifier.fillMaxWidth()) {
        AppListStateContent(
            modifier = Modifier.padding(AppSpacing.cardPaddingSmall),
            state = AppListStateSpec(
                isEmpty = true,
                loading = loading,
                emptyText = stringResource(R.string.receivables_empty_body),
                emptyTitle = stringResource(R.string.receivables_empty_title),
                emptyBody = stringResource(R.string.receivables_empty_body),
            ),
            message = error?.let { AppListStateMessage(text = it, tone = MessageTone.Danger) },
        ) {
        }
    }
}
