package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.RepaymentDraftActions
import com.ticketbox.data.repository.ReportsActions
import com.ticketbox.domain.model.DashboardSurface
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
)

class StatsReportsViewModel(
    private val reportsRepository: ReportsActions? = null,
    // 轨道2 [P1] 还款待确认 badge：pending 还款草稿计数源（菜单「还款待确认」项的 badge）。可空使只传
    // reportsRepository 的构造点（预览/部分测试）无需具名；为空时计数加载整段 no-op。
    private val repaymentDrafts: RepaymentDraftActions? = null,
) : ViewModel() {
    private val _uiState = MutableStateFlow(StatsReportsUiState())
    val uiState: StateFlow<StatsReportsUiState> = _uiState.asStateFlow()
    private var requestGeneration = 0L

    // 还款待确认 badge 计数的独立代际令牌（与 reports/dashboard 的 requestGeneration 解耦——两者各自的慢加载
    // 互不干扰）。被新一轮计数加载超越的旧结果按它丢弃，避免跨账本陈旧计数回灌（switch 后旧账本的慢 GET
    // 落地时已不再是最新一代）。
    private var countGeneration = 0L
    private var inFlightRefreshKey: StatsReportsRefreshKey? = null

    // 轴3 粒度切换:本 VM 是粒度的唯一持有方,UI 的 selected 用服务端回显
    // (overview.granularity)而非另存 state 字段——加载中 segmented 短暂显示旧值可接受。
    private var granularity: ReportGranularity = ReportGranularity.Day

    fun refresh(month: String, selectedTag: String) {
        val selectedMonth = month.trim().ifBlank { YearMonth.now().toString() }
        val cleanTag = selectedTag.trim()
        _uiState.update {
            it.copy(
                month = selectedMonth,
                selectedTag = cleanTag,
            )
        }
        // 还款待确认 badge 计数是**账本作用域**（与月/标签无关），故在 tag 分支与 reportsRepository 空检查
        // **之前**无条件拉：标签筛选态下 badge 仍要显示，且 reportsRepository==null 的构造点也该有计数。
        // refresh 在账本就绪/切换、月/标签变化、下拉刷新、以及 StatsRoute 离/重入 composition（overlay 关闭）
        // 时都会被调，故计数随之刷新——这正是「在复核箱里 confirm/dismiss 后页级 badge 要更新」的刷新协调，
        // 无需跨 VM 信号通道（详见 StatsRoute 的 reports refresh effect）。
        loadPendingDraftCount()
        val reportsRepo = reportsRepository ?: run {
            clearReportSlice()
            return
        }
        val key = StatsReportsRefreshKey(selectedMonth, cleanTag, granularity)
        if (inFlightRefreshKey == key) return
        requestGeneration += 1
        val generation = requestGeneration
        inFlightRefreshKey = key
        if (cleanTag.isBlank()) {
            loadDashboardCards(reportsRepo, generation)
            loadReports(reportsRepo, generation, key)
        } else {
            loadDashboardCards(reportsRepo, generation, finishKey = key)
            clearReportSlice()
        }
    }

    /**
     * 拉 pending 还款草稿数 → [StatsReportsUiState.pendingRepaymentDraftCount]。**仅成功时覆盖**——失败保留
     * 上次已知值（best-effort badge，不因瞬时网络抖动闪掉）；被新一轮超越的旧结果按 [countGeneration] 丢弃。
     */
    private fun loadPendingDraftCount() {
        val repo = repaymentDrafts ?: return
        countGeneration += 1
        val generation = countGeneration
        viewModelScope.launch {
            val result = repo.listPendingDrafts()
            if (generation != countGeneration) return@launch
            result.onSuccess { drafts ->
                _uiState.update { it.copy(pendingRepaymentDraftCount = drafts.size) }
            }
        }
    }

    /** 轴3 粒度切换:置粒度并按当前月重拉报表(标签筛选态没有报表面,直接忽略)。 */
    fun setGranularity(value: ReportGranularity) {
        if (value == granularity) return
        granularity = value
        val state = _uiState.value
        val reportsRepo = reportsRepository ?: return
        if (state.month.isBlank() || state.selectedTag.isNotBlank()) return
        val key = StatsReportsRefreshKey(state.month, "", granularity)
        if (inFlightRefreshKey == key) return
        requestGeneration += 1
        inFlightRefreshKey = key
        loadReports(reportsRepo, requestGeneration, key)
    }

    private fun clearReportSlice() {
        _uiState.update {
            it.copy(
                reportsOverview = null,
                reportGoals = emptyList(),
                reportsLoading = false,
                reportsMessage = null,
            )
        }
    }

    private fun loadDashboardCards(
        reportsRepo: ReportsActions,
        generation: Long,
        finishKey: StatsReportsRefreshKey? = null,
    ) {
        viewModelScope.launch {
            try {
                _uiState.update {
                    it.copy(
                        dashboardCardsLoading = true,
                        dashboardCardsMessage = null,
                    )
                }
                val result = reportsRepo.dashboardCards(DashboardSurface.Android)
                if (!isCurrent(generation)) return@launch
                result
                    .onSuccess { cards ->
                        _uiState.update {
                            it.copy(
                                dashboardCards = cards.items,
                                dashboardCardsLoading = false,
                                dashboardCardsMessage = null,
                            )
                        }
                    }
                    .onFailure { error ->
                        _uiState.update {
                            it.copy(
                                dashboardCardsLoading = false,
                                dashboardCardsMessage = error.toUiText(R.string.stats_message_dashboard_cards_failed),
                            )
                        }
                    }
            } finally {
                finishKey?.let { finishRefresh(it) }
            }
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
                _uiState.update { it.copy(reportsLoading = true, reportsMessage = null) }
                val goalsDeferred = async { reportsRepo.goals(month = key.month) }
                val overviewResult = reportsRepo.reportsOverview(
                    ReportsOverviewQuery(
                        month = key.month,
                        granularity = key.granularity,
                        rankingMetric = ReportRankingMetric.Count,
                    ),
                )
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
                        reportGoals = goalsResult.getOrDefault(emptyList()),
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
