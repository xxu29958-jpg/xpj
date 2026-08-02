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
import com.ticketbox.ui.components.AppAdaptivePaneScaffold
import com.ticketbox.ui.components.AppAdaptivePanePurpose
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
import com.ticketbox.ui.screens.stats.EmptyStatsCard
import com.ticketbox.ui.screens.stats.StatsTopPanel
import com.ticketbox.ui.screens.stats.StatsTopPanelActions
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalAppAdaptiveLayoutPolicy
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
    AppAdaptivePaneScaffold(
        structure = AppAdaptivePaneStructures.Insights,
        policy = adaptivePolicy,
        primaryPane = {
            StatsPrimaryPane(
                paneState = paneState,
                paneActions = paneActions,
                showSupportingPane = adaptivePolicy.showsSupportingPane,
            )
        },
        supportingPane = appAdaptiveSupportingPaneContent(
            purpose = AppAdaptivePanePurpose.InsightControls,
        ) {
            AppAdaptiveSupportingPane(role = AppPageRole.Stats) {
                StatsAdaptiveControls(
                    paneState = paneState,
                    paneActions = paneActions,
                )
            }
        },
    )
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
    showSupportingPane: Boolean,
) {
    val state = paneState.screenState
    val actions = paneActions.screenActions
    AppScrollableContent(
        chrome = AppScrollableContentChrome(
            role = AppPageRole.Stats,
            layout = AppScrollableContentLayout(
                horizontalPadding = AppSpacing.cardPaddingSmall,
                verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
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
        if (!showSupportingPane) {
            item {
                StatsAdaptiveControls(
                    paneState = paneState,
                    paneActions = paneActions,
                )
            }
        }

        val stats = state.stats
        if (stats == null) {
            item {
                when {
                    state.loading -> StatsProductLoadingState()
                    state.statsLoadError != null -> AppErrorState(
                        title = stringResource(R.string.stats_error_card_title),
                        body = state.statsLoadError.asString().ifBlank {
                            stringResource(R.string.stats_error_card_body)
                        },
                        onRetry = actions.onRefresh,
                    )
                    else -> EmptyStatsCard(onRefresh = actions.onRefresh)
                }
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

@Composable
private fun StatsAdaptiveControls(
    paneState: StatsAdaptivePaneState,
    paneActions: StatsAdaptivePaneActions,
) {
    val state = paneState.screenState
    val actions = paneActions.screenActions
    Column(
        verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
    ) {
        StatsTopPanel(
            state = state,
            selectedTab = paneState.selectedTab,
            actions = StatsTopPanelActions(
                onOpenMonthPicker = paneActions.onOpenMonthPicker,
                onTagChange = actions.filters.onTagChange,
                onTabChange = paneActions.onTabChange,
            ),
        )
        statsAuthorityTone(state)?.takeIf { it != DataAuthorityTone.Backend }?.let { tone ->
            AppDataAuthorityStrip(tone = tone)
        }
        state.message?.let { message ->
            AppStatusBanner(message = message, tone = MessageTone.Neutral)
        }
        if (paneState.selectedTab == StatsTab.Trend) {
            reportsTrendStatusMessage(state)?.let { message ->
                AppStatusBanner(message = message, tone = MessageTone.Danger)
            }
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
