package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.domain.model.DailySpend
import com.ticketbox.domain.model.LifestyleStats
import com.ticketbox.domain.model.MonthlyStats
import com.ticketbox.domain.model.recentDailySpending
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.time.YearMonth

data class StatsUiState(
    val stats: MonthlyStats? = null,
    val lifestyleStats: LifestyleStats? = null,
    val dailyTrend: List<DailySpend> = emptyList(),
    val months: List<String> = emptyList(),
    val month: String = YearMonth.now().toString(),
    val loading: Boolean = false,
    val message: String? = null,
)

class StatsViewModel(
    private val repository: ExpenseRepository,
) : ViewModel() {
    private val _uiState = MutableStateFlow(StatsUiState())
    val uiState: StateFlow<StatsUiState> = _uiState.asStateFlow()

    init {
        loadMonths()
        observeDailyTrend()
        refresh()
    }

    private fun loadMonths() {
        viewModelScope.launch {
            repository.months()
                .onSuccess { months -> _uiState.update { it.copy(months = months) } }
        }
    }

    private fun observeDailyTrend() {
        viewModelScope.launch {
            repository.observeConfirmed().collect { expenses ->
                _uiState.update { it.copy(dailyTrend = recentDailySpending(expenses)) }
            }
        }
    }

    fun setMonth(value: String) {
        _uiState.update { it.copy(month = value) }
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            _uiState.update { it.copy(loading = true, message = null) }
            val month = _uiState.value.month.trim().ifBlank { null }
            repository.monthlyStats(month)
                .onSuccess { stats ->
                    repository.lifestyleStats(month)
                        .onSuccess { lifestyle ->
                            repository.syncConfirmed(month)
                            _uiState.update {
                                it.copy(stats = stats, lifestyleStats = lifestyle, loading = false)
                            }
                        }
                        .onFailure { error ->
                            _uiState.update {
                                it.copy(
                                    stats = stats,
                                    loading = false,
                                    message = error.message ?: "生活统计加载失败",
                                )
                            }
                        }
                }
                .onFailure { error -> _uiState.update { it.copy(loading = false, message = error.message ?: "统计加载失败") } }
        }
    }
}
