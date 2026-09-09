package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.ReportsActions
import com.ticketbox.domain.model.ReportGranularity
import com.ticketbox.domain.model.ReportRankingMetric
import com.ticketbox.domain.model.ReportsOverviewQuery
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.time.YearMonth

internal data class StatsReportsRefreshKey(val binding: LogicalSessionBinding, val query: ReportsOverviewQuery)

class StatsReportsViewModel(internal val reportsRepository: ReportsActions? = null) : ViewModel() {
    internal val _uiState = MutableStateFlow(StatsReportsUiState(binding = reportsRepository?.dashboardAccess()?.binding))
    val uiState: StateFlow<StatsReportsUiState> = _uiState.asStateFlow()
    private var requestGeneration = 0L
    private var inFlightRefreshKey: StatsReportsRefreshKey? = null
    private var selection = ReportsOverviewQuery()

    init {
        viewModelScope.launch {
            reportsRepository?.observeReportsAccess()?.distinctUntilChanged()?.collect { access ->
                if (_uiState.value.binding == access?.binding) return@collect
                requestGeneration += 1
                inFlightRefreshKey = null
                selection = selection.copy(homeCurrencyCode = null, timezone = null, merchantCategory = null)
                _uiState.update { StatsReportsUiState(month = it.month, selectedTag = it.selectedTag, binding = access?.binding) }
                if (access != null) refresh(_uiState.value.month, _uiState.value.selectedTag)
            }
        }
    }

    fun refresh(month: String, selectedTag: String) {
        val selectedMonth = runCatching { YearMonth.parse(month.trim()).toString() }.getOrNull() ?: return
        val cleanTag = selectedTag.trim()
        if (_uiState.value.month != selectedMonth || _uiState.value.selectedTag != cleanTag) {
            _uiState.update { StatsReportsUiState(month = selectedMonth, selectedTag = cleanTag, binding = it.binding) }
        }
        selection = selection.copy(month = selectedMonth)
        if (cleanTag.isNotBlank()) {
            requestGeneration += 1
            inFlightRefreshKey = null
            return
        }
        val binding = _uiState.value.binding ?: return
        val repo = reportsRepository ?: return
        val key = StatsReportsRefreshKey(binding, selection)
        if (inFlightRefreshKey == key) return
        inFlightRefreshKey = key
        loadReports(repo, ++requestGeneration, key)
    }

    fun setGranularity(value: ReportGranularity) = select(selection.copy(granularity = value))
    fun setRankingMetric(value: ReportRankingMetric) = select(selection.copy(rankingMetric = value))
    fun setMerchantCategory(value: String?) = select(selection.copy(merchantCategory = value?.trim()?.takeIf { it.isNotEmpty() }))

    private fun select(query: ReportsOverviewQuery) {
        if (selection == query) return
        selection = query
        refresh(_uiState.value.month, _uiState.value.selectedTag)
    }

    private fun loadReports(repo: ReportsActions, generation: Long, key: StatsReportsRefreshKey) {
        viewModelScope.launch {
            try {
                _uiState.update { it.copy(reportGoalsLoadState = ReportGoalsLoadState.Loading, reportsLoading = true, reportsMessage = null) }
                val goals = async { repo.goals(month = key.query.month) }
                val result = repo.reportsOverview(key.query, key.binding)
                if (!isCurrent(generation, key.binding)) {
                    goals.cancel()
                    return@launch
                }
                result.getOrNull()?.let { selection = selection.copy(homeCurrencyCode = it.homeCurrencyCode, timezone = it.timezone) }
                _uiState.update { it.copy(reportsOverview = result.getOrNull(), reportsLoading = false,
                    reportsMessage = result.exceptionOrNull()?.toUiText(R.string.stats_message_trend_failed)) }
                val goalResult = goals.await()
                if (!isCurrent(generation, key.binding)) return@launch
                _uiState.update { it.copy(reportGoals = goalResult.getOrNull() ?: it.reportGoals,
                    reportGoalsLoadState = if (goalResult.isSuccess) ReportGoalsLoadState.Loaded else ReportGoalsLoadState.Failed,
                    reportsMessage = if (result.isFailure && goalResult.isFailure) UiText.res(R.string.stats_message_reports_failed)
                        else it.reportsMessage) }
            } finally {
                if (inFlightRefreshKey == key) inFlightRefreshKey = null
            }
        }
    }

    private fun isCurrent(generation: Long, binding: LogicalSessionBinding): Boolean =
        generation == requestGeneration && _uiState.value.binding == binding && reportsRepository?.dashboardAccess()?.binding == binding

    internal fun currentExportQuery(): ReportsOverviewQuery? {
        val state = _uiState.value
        val overview = state.reportsOverview ?: return null
        if (state.reportsLoading || state.selectedTag.isNotEmpty()) return null
        return selection.copy(month = overview.month, homeCurrencyCode = overview.homeCurrencyCode,
            granularity = overview.granularity, rankingMetric = overview.rankingMetric, merchantCategory = overview.merchantCategory)
    }
}
