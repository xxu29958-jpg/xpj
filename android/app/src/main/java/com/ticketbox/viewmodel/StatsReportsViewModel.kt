package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.ReportsActions
import com.ticketbox.domain.model.ReportGranularity
import com.ticketbox.domain.model.ReportRankingMetric
import com.ticketbox.domain.model.ReportsOverviewQuery
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.time.YearMonth

private data class StatsReportsRefreshKey(
    val month: String,
    val selectedTag: String,
    val granularity: ReportGranularity,
    val rankingMetric: ReportRankingMetric,
)

class StatsReportsViewModel(
    private val reportsRepository: ReportsActions? = null,
) : ViewModel() {
    private val _uiState = MutableStateFlow(StatsReportsUiState())
    val uiState: StateFlow<StatsReportsUiState> = _uiState.asStateFlow()
    private var requestGeneration = 0L

    private var inFlightRefreshKey: StatsReportsRefreshKey? = null

    // 轴3 粒度切换:本 VM 是粒度的唯一持有方,UI 的 selected 用服务端回显
    // (overview.granularity)而非另存 state 字段——加载中 segmented 短暂显示旧值可接受。
    private var granularity: ReportGranularity = ReportGranularity.Day
    private var rankingMetric: ReportRankingMetric = ReportRankingMetric.Count

    fun refresh(month: String, selectedTag: String) {
        val selectedMonth = month.trim().ifBlank { YearMonth.now().toString() }
        val cleanTag = selectedTag.trim()
        _uiState.update {
            it.copy(
                month = selectedMonth,
                selectedTag = cleanTag,
            )
        }
        val reportsRepo = reportsRepository ?: run {
            clearReportSlice()
            return
        }
        val key = currentRefreshKey(selectedMonth, cleanTag)
        if (inFlightRefreshKey == key) return
        requestGeneration += 1
        val generation = requestGeneration
        inFlightRefreshKey = key
        if (cleanTag.isBlank()) {
            loadReports(reportsRepo, generation, key)
        } else {
            clearReportSlice()
            finishRefresh(key)
        }
    }

    /** 轴3 粒度切换:置粒度并按当前月重拉报表(标签筛选态没有报表面,直接忽略)。 */
    fun setGranularity(value: ReportGranularity) {
        if (value == granularity) return
        granularity = value
        val state = _uiState.value
        val reportsRepo = reportsRepository ?: return
        if (state.month.isBlank() || state.selectedTag.isNotBlank()) return
        val key = currentRefreshKey(state.month, "")
        if (inFlightRefreshKey == key) return
        requestGeneration += 1
        inFlightRefreshKey = key
        loadReports(reportsRepo, requestGeneration, key)
    }

    fun setRankingMetric(value: ReportRankingMetric) {
        if (value == rankingMetric) return
        rankingMetric = value
        val state = _uiState.value
        val reportsRepo = reportsRepository ?: return
        if (state.month.isBlank() || state.selectedTag.isNotBlank()) return
        val key = currentRefreshKey(state.month, "")
        if (inFlightRefreshKey == key) return
        requestGeneration += 1
        inFlightRefreshKey = key
        loadReports(reportsRepo, requestGeneration, key)
    }

    private fun currentRefreshKey(month: String, selectedTag: String): StatsReportsRefreshKey =
        StatsReportsRefreshKey(
            month = month,
            selectedTag = selectedTag,
            granularity = granularity,
            rankingMetric = rankingMetric,
        )

    private fun clearReportSlice() {
        _uiState.update {
            it.copy(
                reportsOverview = null,
                reportGoals = emptyList(),
                reportGoalsLoadState = ReportGoalsLoadState.Unknown,
                reportsLoading = false,
                reportsMessage = null,
            )
        }
    }

    private fun finishRefresh(key: StatsReportsRefreshKey) {
        if (inFlightRefreshKey == key) {
            inFlightRefreshKey = null
        }
    }

    private fun loadReports(
        reportsRepo: ReportsActions,
        generation: Long,
        key: StatsReportsRefreshKey,
    ) {
        viewModelScope.launch {
            try {
                _uiState.update {
                    it.copy(
                        reportGoalsLoadState = ReportGoalsLoadState.Loading,
                        reportsLoading = true,
                        reportsMessage = null,
                    )
                }
                val goalsDeferred = async { reportsRepo.goals(month = key.month) }
                val query = ReportsOverviewQuery(month = key.month, granularity = key.granularity, rankingMetric = key.rankingMetric)
                val overviewResult = reportsRepo.reportsOverview(query)
                if (!isCurrent(generation)) {
                    goalsDeferred.cancel()
                    return@launch
                }
                _uiState.update {
                    it.copy(
                        reportsOverview = overviewResult.getOrNull(),
                        reportsLoading = false,
                        reportsMessage = if (overviewResult.isFailure) {
                            UiText.res(R.string.stats_message_trend_failed)
                        } else {
                            null
                        },
                    )
                }

                val goalsResult = goalsDeferred.await()
                if (!isCurrent(generation)) return@launch
                _uiState.update {
                    it.copy(
                        reportGoals = goalsResult.getOrNull() ?: it.reportGoals,
                        reportGoalsLoadState = if (goalsResult.isSuccess) ReportGoalsLoadState.Loaded else ReportGoalsLoadState.Failed,
                        reportsMessage = when {
                            overviewResult.isFailure && goalsResult.isFailure ->
                                UiText.res(R.string.stats_message_reports_failed)
                            overviewResult.isFailure -> UiText.res(R.string.stats_message_trend_failed)
                            else -> null
                        },
                    )
                }
            } finally {
                finishRefresh(key)
            }
        }
    }

    private fun isCurrent(generation: Long): Boolean = generation == requestGeneration
}
