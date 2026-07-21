package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
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
 * 发现 + 确认面。服务端汇总当前主体在所选账本内与跨账本的应收；成员关系行与 external 会计行复用
 * [debtRowsSection]，客户端不从 owner-relative direction 推断主体角色。
 *
 * 行 tap 进入同一 Debt 的详情；跨账本 member creditor 可在那里确认/拒绝还款 proposal，external 与
 * 同账本 member 行沿用既有详情能力。导航由 [com.ticketbox.ui.navigation.ReceivablesRoute] 持有。
 */
@Composable
fun ReceivablesScreen(
    viewModel: ReceivablesViewModel,
    currency: CurrencyDisplay,
    onOpenReceivable: (Debt) -> Unit,
    onBack: () -> Unit,
    chromeOverride: RelationsListChrome? = null,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val resolvedChrome = chromeOverride ?: RelationsListChrome(
        title = stringResource(R.string.receivables_topbar_title),
        subtitle = stringResource(R.string.receivables_intro_body),
        backText = stringResource(R.string.debt_list_topbar_back),
        onBack = onBack,
    )

    AppSecondaryScrollableContent(
        chrome = AppSecondaryPageChrome(
            role = AppPageRole.Ledger,
            title = resolvedChrome.title,
            subtitle = resolvedChrome.subtitle,
            backText = resolvedChrome.backText,
            onBack = resolvedChrome.onBack,
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
        resolvedChrome.domainNavigation?.let { navigation ->
            item(key = "obligations-domain-navigation") { navigation() }
        }
        readableListInlineError(hasRows = state.receivables.isNotEmpty(), error = state.error)?.let { err ->
            item { AppStatusBanner(message = err, tone = MessageTone.Danger) }
        }
        receivablesSection(
            state = state,
            currency = currency,
            onOpenReceivable = onOpenReceivable,
        )
    }
}
private fun LazyListScope.receivablesSection(
    state: ReceivablesUiState,
    currency: CurrencyDisplay,
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
    debtRowsSection(
        debts = state.receivables,
        currency = currency,
        onOpenDebt = onOpenReceivable,
    )
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
