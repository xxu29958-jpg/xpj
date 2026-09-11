package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.StatsActions
import com.ticketbox.data.repository.StatsQuery
import com.ticketbox.data.repository.ReadSnapshot
import com.ticketbox.domain.model.MonthlyStats
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.time.YearMonth

private data class MonthlyStatsRefreshSnapshot(val generation: Long, val query: StatsQuery)

class MonthlyStatsViewModel(
    private val repository: StatsActions,
    initialMonth: String = YearMonth.now().toString(),
) : ViewModel() {
    private val _uiState = MutableStateFlow(MonthlyStatsUiState(month = initialMonth))
    val uiState: StateFlow<MonthlyStatsUiState> = _uiState.asStateFlow()
    private var refreshGeneration = 0L
    private var inFlightRefresh: MonthlyStatsRefreshSnapshot? = null

    init {
        viewModelScope.launch {
            repository.observeStatsBinding().distinctUntilChanged().collect { binding ->
                refreshGeneration += 1
                inFlightRefresh = null
                _uiState.update {
                    MonthlyStatsUiState(month = it.month, selectedTag = it.selectedTag,
                        binding = binding, ledgerReady = binding != null)
                }
                if (binding != null) {
                    loadMonths()
                    loadTags()
                    refresh()
                }
            }
        }
    }

    private fun loadMonths() {
        val binding = _uiState.value.binding ?: return
        viewModelScope.launch {
            _uiState.update { it.copy(monthsLoadState = StatsFilterOptionsLoadState.Loading) }
            val result = repository.months()
            if (!isBindingCurrent(binding)) return@launch
            result.onSuccess { months ->
                _uiState.update { it.copy(months = statsMonthOptions(months, it.month),
                    monthsLoadState = StatsFilterOptionsLoadState.Loaded) }
            }.onFailure {
                _uiState.update { it.copy(monthsLoadState = StatsFilterOptionsLoadState.Failed) }
            }
        }
    }

    private fun loadTags() {
        val binding = _uiState.value.binding ?: return
        viewModelScope.launch {
            _uiState.update { it.copy(tagsLoadState = StatsFilterOptionsLoadState.Loading) }
            val result = repository.tags()
            if (!isBindingCurrent(binding)) return@launch
            result.onSuccess { tags ->
                _uiState.update { it.copy(tags = tags, tagsLoadState = StatsFilterOptionsLoadState.Loaded) }
            }.onFailure {
                _uiState.update { it.copy(tagsLoadState = StatsFilterOptionsLoadState.Failed) }
            }
        }
    }

    fun reloadTags() = loadTags()

    fun setMonth(value: String) {
        if (runCatching { YearMonth.parse(value) }.isFailure || value == _uiState.value.month) return
        changeQuery(value, _uiState.value.selectedTag)
    }

    fun setTag(value: String) {
        val tag = value.trim()
        if (tag == _uiState.value.selectedTag) return
        changeQuery(_uiState.value.month, tag)
    }

    private fun changeQuery(month: String, tag: String) {
        refreshGeneration += 1
        inFlightRefresh = null
        _uiState.update {
            it.copy(month = month, selectedTag = tag, months = statsMonthOptions(it.months, month),
                stats = null, statsSource = StatsSource.None, statsFetchedAt = null,
                lifestyleStats = null, lifestyleFetchedAt = null, lifestyleFromCache = false,
                statsLoadError = null, message = null, loading = false)
        }
        refresh()
    }

    fun refresh() {
        val state = _uiState.value
        val binding = state.binding ?: return
        val query = StatsQuery(binding, state.month, state.selectedTag, state.homeCurrencyCode, state.timezone)
        if (inFlightRefresh?.query == query) return
        val snapshot = MonthlyStatsRefreshSnapshot(++refreshGeneration, query)
        inFlightRefresh = snapshot
        viewModelScope.launch {
            try {
                _uiState.update { it.copy(loading = true, message = null, statsLoadError = null,
                    lastUploadAt = repository.lastUploadAt()) }
                val result = repository.monthlyStats(query)
                if (!snapshot.isCurrent()) return@launch
                result.onSuccess { read -> handleStatsSuccess(read, snapshot) }
                    .onFailure { error -> handleStatsFailure(error, snapshot) }
            } finally {
                if (inFlightRefresh == snapshot) inFlightRefresh = null
            }
        }
    }

    private fun handleStatsSuccess(read: ReadSnapshot<MonthlyStats>, snapshot: MonthlyStatsRefreshSnapshot) {
        _uiState.update {
            it.copy(stats = read.value, statsFetchedAt = read.fetchedAt,
                statsSource = if (read.fromCache) StatsSource.CachedSnapshot else StatsSource.Backend,
                homeCurrencyCode = read.value.homeCurrencyCode, loading = false, statsLoadError = null,
                primaryRefreshRevision = it.primaryRefreshRevision + 1)
        }
        loadDataQuality(snapshot)
        if (snapshot.query.tag.isBlank()) loadLifestyle(snapshot, read.value.homeCurrencyCode)
        if (!read.fromCache) viewModelScope.launch {
            if (snapshot.isCurrent()) repository.syncConfirmed(snapshot.query.month, null, snapshot.query.tag.ifBlank { null })
        }
    }

    private fun handleStatsFailure(error: Throwable, snapshot: MonthlyStatsRefreshSnapshot) {
        if (clearRejectedRead(error)) return
        _uiState.update {
            it.copy(loading = false, statsSource = if (it.stats == null) StatsSource.None else StatsSource.CachedSnapshot,
                lifestyleFromCache = it.lifestyleStats != null,
                statsLoadError = if (it.stats == null) error.toUiText(R.string.stats_message_stats_failed) else null,
                message = if (it.stats == null) null else error.toUiText(R.string.stats_message_stats_failed))
        }
        loadDataQuality(snapshot)
    }

    private fun clearRejectedRead(error: Throwable): Boolean {
        if (!error.isReadAccessDenied()) return false
        // Invalidate any parallel response admitted before this explicit refusal.
        refreshGeneration += 1
        inFlightRefresh = null
        _uiState.update { it.copy(stats = null, statsFetchedAt = null, statsSource = StatsSource.None,
            lifestyleStats = null, lifestyleFetchedAt = null, lifestyleFromCache = false,
            loading = false, statsLoadError = error.toUiText(R.string.stats_message_stats_failed), message = null) }
        return true
    }

    private fun loadLifestyle(snapshot: MonthlyStatsRefreshSnapshot, homeCurrencyCode: String) {
        viewModelScope.launch {
            val result = repository.lifestyleStats(snapshot.query.copy(homeCurrencyCode = homeCurrencyCode))
            if (!snapshot.isCurrent()) return@launch
            result.onSuccess { read ->
                _uiState.update { it.copy(lifestyleStats = read.value, lifestyleFetchedAt = read.fetchedAt,
                    lifestyleFromCache = read.fromCache) }
            }.onFailure { error ->
                if (clearRejectedRead(error)) return@launch
                _uiState.update { it.copy(lifestyleFromCache = it.lifestyleStats != null,
                    message = error.toUiText(R.string.stats_message_lifestyle_failed)) }
            }
        }
    }

    private fun loadDataQuality(snapshot: MonthlyStatsRefreshSnapshot) {
        viewModelScope.launch {
            _uiState.update { it.copy(dataQualityLoadState = DataQualityLoadState.Loading, dataQualityError = null) }
            val result = repository.dataQualitySummary()
            if (!snapshot.isCurrent()) return@launch
            result.onSuccess { summary ->
                _uiState.update { it.copy(dataQuality = summary, dataQualityLoadState = DataQualityLoadState.Loaded,
                    dataQualityError = null) }
            }.onFailure { error ->
                _uiState.update { it.copy(dataQualityLoadState = DataQualityLoadState.Failed,
                    dataQualityError = error.toUiText(R.string.stats_data_quality_load_failed)) }
            }
        }
    }

    private fun isBindingCurrent(binding: LogicalSessionBinding): Boolean =
        _uiState.value.binding == binding && repository.statsBinding() == binding

    private fun MonthlyStatsRefreshSnapshot.isCurrent(): Boolean {
        val state = _uiState.value
        return generation == refreshGeneration && isBindingCurrent(query.binding) &&
            state.month == query.month && state.selectedTag == query.tag && state.timezone == query.timezone
    }
}

private fun statsMonthOptions(authoritativeMonths: List<String>, selectedMonth: String): List<String> {
    val requiredMonth = selectedMonth.trim().ifBlank { YearMonth.now().toString() }
    val remainingMonths = authoritativeMonths
        .map { it.trim() }
        .filter { it.isNotBlank() }
        .distinct()
        .filterNot { it == requiredMonth }
        .sortedWith(::compareStatsMonthDescending)
    return listOf(requiredMonth) + remainingMonths
}

private fun compareStatsMonthDescending(left: String, right: String): Int {
    val leftMonth = parseStatsMonth(left)
    val rightMonth = parseStatsMonth(right)
    return when {
        leftMonth != null && rightMonth != null -> rightMonth.compareTo(leftMonth)
        leftMonth != null -> -1
        rightMonth != null -> 1
        else -> left.compareTo(right)
    }
}

private fun parseStatsMonth(value: String): YearMonth? =
    runCatching { YearMonth.parse(value) }.getOrNull()
