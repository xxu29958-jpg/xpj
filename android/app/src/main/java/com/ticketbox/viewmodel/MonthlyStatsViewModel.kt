package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.RecurringActions
import com.ticketbox.data.repository.StatsActions
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.MonthlyStats
import com.ticketbox.domain.model.UiText
import com.ticketbox.domain.model.filterConfirmedExpenses
import com.ticketbox.domain.model.monthlyCategoryInsight
import com.ticketbox.domain.model.monthlyStatsFromConfirmedExpenses
import com.ticketbox.domain.model.monthlySpendingComparison
import com.ticketbox.domain.model.recentDailySpending
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.YearMonth
import java.time.ZoneId

private data class MonthlyStatsRefreshSnapshot(
    val generation: Long,
    val ledgerId: String?,
    val month: String,
    val selectedTag: String,
)

class MonthlyStatsViewModel(
    private val repository: StatsActions,
    private val recurringRepository: RecurringActions,
) : ViewModel() {
    private val _uiState = MutableStateFlow(MonthlyStatsUiState())
    val uiState: StateFlow<MonthlyStatsUiState> = _uiState.asStateFlow()
    private var confirmedCache: List<Expense> = emptyList()
    private var activeLedgerId: String? = null
    private var refreshGeneration = 0L
    private var observedLedgerOnce = false

    init {
        observeLedgerChanges()
        observeDailyTrend()
    }

    private fun observeLedgerChanges() {
        viewModelScope.launch {
            repository.observeActiveLedgerId()
                .distinctUntilChanged()
                .collect { ledgerId ->
                    val normalizedLedgerId = ledgerId?.takeIf { it.isNotBlank() }
                    if (observedLedgerOnce && activeLedgerId == normalizedLedgerId) {
                        return@collect
                    }
                    observedLedgerOnce = true
                    activeLedgerId = normalizedLedgerId
                    refreshGeneration += 1
                    confirmedCache = emptyList()
                    _uiState.update {
                        it.copy(
                            stats = null,
                            statsSource = StatsSource.None,
                            lifestyleStats = null,
                            dailyTrend = emptyList(),
                            monthComparison = null,
                            categoryInsight = null,
                            recurringItems = emptyList(),
                            recurringCandidates = emptyList(),
                            dataQuality = null,
                            loading = false,
                            message = null,
                            statsLoadError = null,
                            ledgerReady = true,
                            activeLedgerId = normalizedLedgerId,
                        )
                    }
                    loadMonths()
                    loadTags()
                    refresh()
                }
        }
    }

    private fun loadMonths() {
        viewModelScope.launch {
            repository.months()
                .onSuccess { months ->
                    _uiState.update { state ->
                        state.copy(months = statsMonthOptions(months, state.month))
                    }
                }
        }
    }

    private fun loadTags() {
        viewModelScope.launch {
            repository.tags()
                .onSuccess { tags -> _uiState.update { it.copy(tags = tags) } }
        }
    }

    /**
     * Re-pull the authoritative tag list. Tags are otherwise loaded only on init /
     * ledger switch (P4 stale-refresh): after a tag is deleted/renamed/merged in
     * settings, the stats filter chips kept showing the dead tag because this VM
     * persists across the settings round-trip and never re-pulled. StatsRoute calls
     * this on the cross-screen refresh signal and on pull-to-refresh; the resync of
     * de-tagged expenses (the byTag chip source) already rides refresh()'s
     * syncConfirmed.
     */
    fun reloadTags() = loadTags()

    private fun observeDailyTrend() {
        viewModelScope.launch {
            repository.observeConfirmed().collect { expenses ->
                confirmedCache = expenses
                _uiState.update {
                    val tagFilteredExpenses = filterConfirmedExpenses(
                        expenses = expenses,
                        month = "",
                        category = "",
                        tag = it.selectedTag,
                    )
                    val localStats = monthlyStatsFromConfirmedExpenses(expenses, it.month, it.selectedTag)
                    val visibleStats = it.stats ?: localStats
                    val nextSource = when {
                        it.stats != null -> it.statsSource
                        visibleStats != null -> StatsSource.LocalFallback
                        else -> StatsSource.None
                    }
                    it.copy(
                        stats = visibleStats,
                        statsSource = nextSource,
                        dailyTrend = localDailyTrend(expenses, it.month, it.selectedTag),
                        monthComparison = monthlySpendingComparison(tagFilteredExpenses, it.month),
                        categoryInsight = monthlyCategoryInsight(visibleStats),
                    )
                }
            }
        }
    }

    fun setMonth(value: String) {
        _uiState.update {
            val tagFilteredExpenses = filterConfirmedExpenses(
                expenses = confirmedCache,
                month = "",
                category = "",
                tag = it.selectedTag,
            )
            val localStats = monthlyStatsFromConfirmedExpenses(confirmedCache, value, it.selectedTag)
            it.copy(
                month = value,
                months = statsMonthOptions(it.months, value),
                stats = localStats,
                statsSource = if (localStats != null) StatsSource.LocalFallback else StatsSource.None,
                dailyTrend = localDailyTrend(confirmedCache, value, it.selectedTag),
                monthComparison = monthlySpendingComparison(tagFilteredExpenses, value),
                categoryInsight = monthlyCategoryInsight(localStats),
            )
        }
        refresh()
    }

    fun setTag(value: String) {
        val cleanTag = value.trim()
        _uiState.update {
            val tagFilteredExpenses = filterConfirmedExpenses(
                expenses = confirmedCache,
                month = "",
                category = "",
                tag = cleanTag,
            )
            val localStats = monthlyStatsFromConfirmedExpenses(confirmedCache, it.month, cleanTag)
            it.copy(
                selectedTag = cleanTag,
                stats = localStats,
                dailyTrend = localDailyTrend(confirmedCache, it.month, cleanTag),
                monthComparison = monthlySpendingComparison(tagFilteredExpenses, it.month),
                categoryInsight = monthlyCategoryInsight(localStats),
            )
        }
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            val snapshot = beginRefreshSnapshot()
            _uiState.update {
                it.copy(
                    loading = true,
                    message = null,
                    statsLoadError = null,
                    lastUploadAt = repository.lastUploadAt(),
                )
            }
            val month = snapshot.month.trim().ifBlank { null }
            val tag = snapshot.selectedTag.trim().ifBlank { null }
            val statsResult = repository.monthlyStats(month = month, tag = tag)
            if (!snapshot.isCurrent()) return@launch
            statsResult
                .onSuccess { stats -> handleStatsSuccess(stats, month, tag, snapshot) }
                .onFailure { error -> handleStatsFailure(error, month, tag, snapshot) }
        }
    }

    private fun loadRecurring(month: String?, snapshot: MonthlyStatsRefreshSnapshot) {
        viewModelScope.launch {
            val result = recurringRepository.items(status = null, includeArchived = false, month = month)
            if (!snapshot.isCurrent()) return@launch
            result.onSuccess { items ->
                _uiState.update { it.copy(recurringItems = items) }
            }
        }
    }

    private fun loadRecurringCandidates(snapshot: MonthlyStatsRefreshSnapshot) {
        viewModelScope.launch {
            val result = recurringRepository.candidates()
            if (!snapshot.isCurrent()) return@launch
            result.onSuccess { items ->
                _uiState.update { it.copy(recurringCandidates = items) }
            }
        }
    }

    private fun loadDataQuality(snapshot: MonthlyStatsRefreshSnapshot) {
        viewModelScope.launch {
            val result = repository.dataQualitySummary()
            if (!snapshot.isCurrent()) return@launch
            result.onSuccess { summary ->
                _uiState.update { it.copy(dataQuality = summary) }
            }
        }
    }

    private fun handleStatsSuccess(
        stats: MonthlyStats,
        month: String?,
        tag: String?,
        snapshot: MonthlyStatsRefreshSnapshot,
    ) {
        if (!snapshot.isCurrent()) return
        _uiState.update {
            it.copy(
                stats = stats,
                statsSource = StatsSource.Backend,
                categoryInsight = monthlyCategoryInsight(stats),
                loading = false,
                statsLoadError = null,
            )
        }
        loadSupplementalAfterPrimaryStats(month, snapshot)
        loadLifestyleAfterPrimaryStats(month, snapshot)
        syncConfirmedAfterPrimaryStats(month, tag, snapshot)
    }

    private fun loadSupplementalAfterPrimaryStats(
        month: String?,
        snapshot: MonthlyStatsRefreshSnapshot,
    ) {
        loadRecurring(month, snapshot)
        loadRecurringCandidates(snapshot)
        loadDataQuality(snapshot)
    }

    private fun loadLifestyleAfterPrimaryStats(
        month: String?,
        snapshot: MonthlyStatsRefreshSnapshot,
    ) {
        viewModelScope.launch {
            val lifestyleResult = repository.lifestyleStats(month)
            if (!snapshot.isCurrent()) return@launch
            lifestyleResult
                .onSuccess { lifestyle ->
                    _uiState.update { it.copy(lifestyleStats = lifestyle) }
                }
                .onFailure { error ->
                    _uiState.update {
                        it.copy(message = error.toUiText(R.string.stats_message_lifestyle_failed))
                    }
                }
        }
    }

    private fun syncConfirmedAfterPrimaryStats(
        month: String?,
        tag: String?,
        snapshot: MonthlyStatsRefreshSnapshot,
    ) {
        viewModelScope.launch {
            if (!snapshot.isCurrent()) return@launch
            repository.syncConfirmed(month = month, category = null, tag = tag)
        }
    }

    private fun handleStatsFailure(
        error: Throwable,
        month: String?,
        tag: String?,
        snapshot: MonthlyStatsRefreshSnapshot,
    ) {
        if (!snapshot.isCurrent()) return
        _uiState.update {
            val fallbackStats = month?.let { value ->
                monthlyStatsFromConfirmedExpenses(confirmedCache, value, tag.orEmpty())
            }
            val visibleStats = fallbackStats ?: it.stats
            val nextSource = when {
                fallbackStats != null -> StatsSource.LocalFallback
                visibleStats != null -> it.statsSource
                else -> StatsSource.None
            }
            it.copy(
                stats = visibleStats,
                statsSource = nextSource,
                categoryInsight = monthlyCategoryInsight(visibleStats),
                loading = false,
                // On total failure the retryable error card below is the single
                // failure surface — also setting message would render the same
                // copy twice on the screen this change exists to clean up.
                message = if (fallbackStats != null) {
                    UiText.res(R.string.stats_message_local_fallback)
                } else {
                    null
                },
                // Only a total failure with nothing to render becomes a retryable error
                // state (audit 8.4); when a local fallback exists the screen shows data +
                // the "本机估算" message, so no error card.
                statsLoadError = if (visibleStats == null) {
                    error.toUiText(R.string.stats_message_stats_failed)
                } else {
                    null
                },
            )
        }
        loadSupplementalAfterPrimaryStats(month, snapshot)
    }

    private fun beginRefreshSnapshot(): MonthlyStatsRefreshSnapshot {
        val state = _uiState.value
        refreshGeneration += 1
        return MonthlyStatsRefreshSnapshot(
            generation = refreshGeneration,
            ledgerId = activeLedgerId,
            month = state.month.ifBlank { YearMonth.now().toString() },
            selectedTag = state.selectedTag.trim(),
        )
    }

    private fun MonthlyStatsRefreshSnapshot.isCurrent(): Boolean {
        val state = _uiState.value
        return generation == refreshGeneration &&
            ledgerId == activeLedgerId &&
            month == state.month &&
            selectedTag == state.selectedTag.trim()
    }

    private fun localDailyTrend(
        expenses: List<Expense>,
        month: String,
        selectedTag: String,
    ) = recentDailySpending(
        expenses = filterConfirmedExpenses(
            expenses = expenses,
            month = month,
            category = "",
            tag = selectedTag,
        ),
        referenceDate = localTrendReferenceDate(month),
    )

    private fun localTrendReferenceDate(month: String): LocalDate {
        val zoneId = ZoneId.systemDefault()
        val today = LocalDate.now(zoneId)
        val selectedMonth = runCatching { YearMonth.parse(month.trim()) }.getOrNull()
            ?: return today
        return if (selectedMonth == YearMonth.from(today)) {
            today
        } else {
            selectedMonth.atEndOfMonth()
        }
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
