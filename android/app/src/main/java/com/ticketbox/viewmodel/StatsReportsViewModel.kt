package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.ReportsActions
import com.ticketbox.domain.model.DashboardSurface
import com.ticketbox.domain.model.ReportGranularity
import com.ticketbox.domain.model.ReportsOverviewQuery
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.time.YearMonth

class StatsReportsViewModel(
    private val reportsRepository: ReportsActions? = null,
) : ViewModel() {
    private val _uiState = MutableStateFlow(StatsReportsUiState())
    val uiState: StateFlow<StatsReportsUiState> = _uiState.asStateFlow()
    private var requestGeneration = 0L

    fun refresh(month: String, selectedTag: String) {
        requestGeneration += 1
        val generation = requestGeneration
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
        loadDashboardCards(reportsRepo, generation)
        if (cleanTag.isBlank()) {
            loadReports(reportsRepo, generation, selectedMonth)
        } else {
            clearReportSlice()
        }
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

    private fun loadDashboardCards(reportsRepo: ReportsActions, generation: Long) {
        viewModelScope.launch {
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
        }
    }

    private fun loadReports(reportsRepo: ReportsActions, generation: Long, month: String) {
        viewModelScope.launch {
            _uiState.update { it.copy(reportsLoading = true, reportsMessage = null) }
            val overviewResult = reportsRepo.reportsOverview(
                ReportsOverviewQuery(
                    month = month,
                    granularity = ReportGranularity.Day,
                ),
            )
            val goalsResult = reportsRepo.goals(month = month)
            if (!isCurrent(generation)) return@launch
            _uiState.update {
                it.copy(
                    reportsOverview = overviewResult.getOrNull(),
                    reportGoals = goalsResult.getOrDefault(emptyList()),
                    reportsLoading = false,
                    reportsMessage = when {
                        overviewResult.isFailure && goalsResult.isFailure ->
                            UiText.res(R.string.stats_message_reports_failed)
                        overviewResult.isFailure -> UiText.res(R.string.stats_message_trend_failed)
                        else -> null
                    },
                )
            }
        }
    }

    private fun isCurrent(generation: Long): Boolean = generation == requestGeneration
}
