package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.MonthComparison
import com.ticketbox.domain.model.ReportGranularity
import com.ticketbox.domain.model.ReportRankingMetric
import com.ticketbox.domain.model.ReportsOverview
import com.ticketbox.domain.model.StatsTab
import com.ticketbox.domain.model.moneyPercent
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppAdaptivePanePurpose
import com.ticketbox.ui.components.AppAdaptivePaneScaffold
import com.ticketbox.ui.components.AppAdaptivePaneStructures
import com.ticketbox.ui.components.AppAdaptiveSupportingPane
import com.ticketbox.ui.components.AppDataAuthorityStrip
import com.ticketbox.ui.components.AppErrorState
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppScrollableContent
import com.ticketbox.ui.components.AppScrollableContentChrome
import com.ticketbox.ui.components.AppScrollableContentLayout
import com.ticketbox.ui.components.AppScrollableRefreshState
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.DataAuthorityTone
import com.ticketbox.ui.components.MonthPickerListState
import com.ticketbox.ui.components.MonthPickerSheet
import com.ticketbox.ui.components.appAdaptiveSupportingPaneContent
import com.ticketbox.ui.design.AppAdaptiveContentWidth
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalAppAdaptiveLayoutPolicy
import com.ticketbox.ui.screens.stats.EmptyStatsCard
import com.ticketbox.ui.screens.stats.StatsFilterControls
import com.ticketbox.ui.screens.stats.StatsViewTabs
import com.ticketbox.viewmodel.StatsFilterOptionsLoadState
import com.ticketbox.viewmodel.StatsSource
import com.ticketbox.viewmodel.StatsUiState

data class StatsScreenActions(
    val filters: StatsFilterActions,
    val onRefresh: () -> Unit,
    val onOpenDataQuality: () -> Unit,
    val reports: StatsReportActions,
)

data class StatsFilterActions(
    val onMonthChange: (String) -> Unit,
    val onTagChange: (String) -> Unit,
)

data class StatsReportActions(
    val onDrillToLedger: (String) -> Unit,
    val onGranularityChange: (ReportGranularity) -> Unit,
    val onRankingMetricChange: (ReportRankingMetric) -> Unit,
)

/**
 * 平窗(Compact/Medium/无竖铰链的 Expanded): 单主列, 筛选+页签+状态贴在结果上方。
 * 真实竖铰链(ExpandedSupporting + vertical hinge, 两个物理半屏): 保留官方双 pane,
 * 左页页签+结果, 右页筛选+状态 —— Insights 结构仅此一个真实 consumer。
 */
private enum class StatsControlsMode { FiltersAndTabs, Tabs }

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun StatsScreen(
    state: StatsUiState,
    actions: StatsScreenActions,
) {
    var showMonthPicker by rememberSaveable { mutableStateOf(false) }
    var selectedStatsTab by rememberSaveable { mutableStateOf(StatsTab.Overview) }

    if (showMonthPicker) {
        ModalBottomSheet(onDismissRequest = { showMonthPicker = false }) {
            MonthPickerSheet(
                months = state.months,
                selectedMonth = state.month,
                description = stringResource(R.string.stats_month_picker_description),
                listState = state.monthPickerListState(),
                onSelectMonth = { month ->
                    actions.filters.onMonthChange(month)
                    showMonthPicker = false
                },
            )
        }
    }

    val adaptivePolicy = LocalAppAdaptiveLayoutPolicy.current
    val paneState = StatsAdaptivePaneState(
        screenState = state,
        selectedTab = selectedStatsTab,
    )
    val paneActions = StatsAdaptivePaneActions(
        screenActions = actions,
        onOpenMonthPicker = { showMonthPicker = true },
        onTabChange = { selectedStatsTab = it },
    )
    if (adaptivePolicy.usesOfficialVerticalHingeBounds) {
        AppAdaptivePaneScaffold(
            structure = AppAdaptivePaneStructures.Insights,
            policy = adaptivePolicy,
            primaryPane = {
                StatsPrimaryPane(
                    paneState = paneState,
                    paneActions = paneActions,
                    controlsMode = StatsControlsMode.Tabs,
                )
            },
            supportingPane = appAdaptiveSupportingPaneContent(
                purpose = AppAdaptivePanePurpose.InsightControls,
            ) {
                AppAdaptiveSupportingPane(role = AppPageRole.Stats) {
                    Column(
                        verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
                    ) {
                        StatsFilterControls(
                            state = paneState.screenState,
                            onOpenMonthPicker = paneActions.onOpenMonthPicker,
                            onTagChange = paneActions.screenActions.filters.onTagChange,
                        )
                        StatsStatusMessages(
                            state = paneState.screenState,
                            selectedTab = paneState.selectedTab,
                        )
                    }
                }
            },
        )
    } else {
        StatsPrimaryPane(
            paneState = paneState,
            paneActions = paneActions,
            controlsMode = StatsControlsMode.FiltersAndTabs,
        )
    }
}

private data class StatsAdaptivePaneState(
    val screenState: StatsUiState,
    val selectedTab: StatsTab,
)

private data class StatsAdaptivePaneActions(
    val screenActions: StatsScreenActions,
    val onOpenMonthPicker: () -> Unit,
    val onTabChange: (StatsTab) -> Unit,
)

@Composable
private fun StatsPrimaryPane(
    paneState: StatsAdaptivePaneState,
    paneActions: StatsAdaptivePaneActions,
    controlsMode: StatsControlsMode,
) {
    val state = paneState.screenState
    val actions = paneActions.screenActions
    AppScrollableContent(
        chrome = AppScrollableContentChrome(
            role = AppPageRole.Stats,
            layout = AppScrollableContentLayout(
                horizontalPadding = AppSpacing.cardPaddingSmall,
                verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
                contentWidth = AppAdaptiveContentWidth.Wide,
            ),
        ),
        refresh = AppScrollableRefreshState(
            isRefreshing = StatsRefreshIndicator.isActive(
                loading = state.loading,
                hasReadableData = state.stats != null,
            ),
            onRefresh = actions.onRefresh,
        ),
    ) {
        item {
            StatsControlsBlock(
                paneState = paneState,
                paneActions = paneActions,
                controlsMode = controlsMode,
            )
        }

        if (state.stats == null) {
            item {
                StatsUnreadableState(state = state, onRefresh = actions.onRefresh)
            }
            return@AppScrollableContent
        }

        statsProductItems(
            state = state,
            selectedTab = paneState.selectedTab,
            actions = actions.reports,
            onOpenDataQuality = actions.onOpenDataQuality,
        )
    }
}

/**
 * 控制块渲染出口：平窗为筛选+页签+状态消息，铰链模式只留页签（筛选与状态在右页）。
 */
@Composable
private fun StatsControlsBlock(
    paneState: StatsAdaptivePaneState,
    paneActions: StatsAdaptivePaneActions,
    controlsMode: StatsControlsMode,
) {
    val state = paneState.screenState
    val actions = paneActions.screenActions
    when (controlsMode) {
        StatsControlsMode.FiltersAndTabs -> Column(
            verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
        ) {
            StatsFilterControls(
                state = state,
                onOpenMonthPicker = paneActions.onOpenMonthPicker,
                onTagChange = actions.filters.onTagChange,
            )
            StatsViewTabs(
                selectedTab = paneState.selectedTab,
                onTabChange = paneActions.onTabChange,
            )
            StatsStatusMessages(
                state = state,
                selectedTab = paneState.selectedTab,
            )
        }

        StatsControlsMode.Tabs -> StatsViewTabs(
            selectedTab = paneState.selectedTab,
            onTabChange = paneActions.onTabChange,
        )
    }
}

/** stats 不可读三态（loading / error / empty），与迁移前逐条一致。 */
@Composable
private fun StatsUnreadableState(
    state: StatsUiState,
    onRefresh: () -> Unit,
) {
    when {
        state.loading -> StatsProductLoadingState()
        state.statsLoadError != null -> AppErrorState(
            title = stringResource(R.string.stats_error_card_title),
            body = state.statsLoadError.asString().ifBlank {
                stringResource(R.string.stats_error_card_body)
            },
            onRetry = onRefresh,
        )
        else -> EmptyStatsCard(onRefresh = onRefresh)
    }
}

/**
 * 来源/离线/通知状态的统一出口：Backend 且无消息时不渲染，避免空容器占位。
 * 口径与迁移前 StatsAdaptiveControls 逐条一致，UI 不现算任何业务事实。
 */
@Composable
private fun StatsStatusMessages(
    state: StatsUiState,
    selectedTab: StatsTab,
) {
    val authorityTone = statsAuthorityTone(state)?.takeIf { it != DataAuthorityTone.Backend }
    val message = state.message
    val trendMessage = if (selectedTab == StatsTab.Trend) {
        reportsTrendStatusMessage(state)
    } else {
        null
    }
    if (authorityTone == null && message == null && trendMessage == null) return
    Column(
        verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
    ) {
        authorityTone?.let { tone ->
            AppDataAuthorityStrip(tone = tone)
        }
        message?.let {
            AppStatusBanner(message = it, tone = MessageTone.Neutral)
        }
        trendMessage?.let {
            AppStatusBanner(message = it, tone = MessageTone.Danger)
        }
    }
}

@Composable
private fun StatsUiState.monthPickerListState(): MonthPickerListState = when (monthsLoadState) {
    StatsFilterOptionsLoadState.Unknown -> MonthPickerListState.Unknown
    StatsFilterOptionsLoadState.Loading -> MonthPickerListState.Loading
    StatsFilterOptionsLoadState.Loaded -> MonthPickerListState.Loaded
    StatsFilterOptionsLoadState.Failed -> MonthPickerListState.Failed
}

private fun statsAuthorityTone(state: StatsUiState): DataAuthorityTone? = when {
    StatsRefreshIndicator.isActive(loading = state.loading, hasReadableData = state.stats != null) ->
        DataAuthorityTone.Refreshing
    state.statsSource == StatsSource.LocalFallback -> DataAuthorityTone.LocalCache
    state.statsSource == StatsSource.Backend -> DataAuthorityTone.Backend
    else -> null
}

internal fun overviewRecent7DaysAmount(state: StatsUiState): Long? {
    if (state.statsSource != StatsSource.Backend || state.selectedTag.isNotBlank()) return null
    return state.lifestyleStats?.recent7DaysAmountCents?.coerceAtLeast(0L)
}

internal fun overviewMonthComparison(state: StatsUiState): MonthComparison? {
    if (state.statsSource != StatsSource.Backend || state.selectedTag.isNotBlank()) return null
    val overview = state.reportsOverview ?: return null
    if (overview.month != state.month) return null
    return overview.toAuthoritativeMonthComparison()
}

private fun ReportsOverview.toAuthoritativeMonthComparison(): MonthComparison? {
    if (previousCount <= 0 || previousTotalAmountCents <= 0L) return null
    val currentAmount = totalAmountCents.coerceAtLeast(0L)
    val delta = currentAmount - previousTotalAmountCents
    return MonthComparison(
        currentMonth = month,
        previousMonth = previousMonth,
        currentAmountCents = currentAmount,
        previousAmountCents = previousTotalAmountCents,
        deltaAmountCents = delta,
        percentChange = moneyPercent(delta, previousTotalAmountCents),
    )
}

internal fun shouldShowReportsUnavailableFallback(state: StatsUiState): Boolean =
    state.reportsOverview == null && state.selectedTag.isBlank() && !state.reportsLoading

internal fun reportsTrendStatusMessage(state: StatsUiState) =
    state.reportsMessage.takeUnless { shouldShowReportsUnavailableFallback(state) }

internal object StatsRefreshIndicator {
    fun isActive(loading: Boolean, hasReadableData: Boolean): Boolean =
        ReadableRefreshIndicator.isActive(loading = loading, hasReadableData = hasReadableData)
}
