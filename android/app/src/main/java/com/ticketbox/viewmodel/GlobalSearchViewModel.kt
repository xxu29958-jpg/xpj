package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.repository.GlobalSearchActions
import com.ticketbox.domain.model.Expense
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

enum class GlobalSearchScope {
    All,
    Pending,
    Confirmed,
}

enum class GlobalSearchResultKind {
    Pending,
    Confirmed,
}

data class GlobalSearchResultUi(
    val kind: GlobalSearchResultKind,
    val expense: Expense,
    val title: String,
    val matchedField: String,
)

data class GlobalSearchUiState(
    val query: String = "",
    val scope: GlobalSearchScope = GlobalSearchScope.All,
    val results: List<GlobalSearchResultUi> = emptyList(),
    val pendingMatchCount: Int = 0,
    val confirmedMatchCount: Int = 0,
    val loadingPending: Boolean = false,
    val pendingLoaded: Boolean = false,
    val message: String? = null,
)

class GlobalSearchViewModel(
    private val repository: GlobalSearchActions,
) : ViewModel() {
    private val _uiState = MutableStateFlow(GlobalSearchUiState())
    val uiState: StateFlow<GlobalSearchUiState> = _uiState.asStateFlow()

    private var pendingCache: List<Expense> = emptyList()
    private var confirmedCache: List<Expense> = emptyList()
    private var requestGeneration = 0

    init {
        viewModelScope.launch {
            repository.observeConfirmed().collect { expenses ->
                confirmedCache = expenses
                recompute()
            }
        }
        viewModelScope.launch {
            repository.observeActiveLedgerId()
                .distinctUntilChanged()
                .drop(1)
                .collect {
                    requestGeneration += 1
                    pendingCache = emptyList()
                    confirmedCache = emptyList()
                    _uiState.update {
                        it.copy(
                            results = emptyList(),
                            pendingMatchCount = 0,
                            confirmedMatchCount = 0,
                            loadingPending = false,
                            pendingLoaded = false,
                            message = null,
                        )
                    }
                    refreshPending()
                }
        }
        refreshPending()
    }

    fun setQuery(value: String) {
        _uiState.update { it.copy(query = value.take(MAX_QUERY_LENGTH)) }
        recompute()
    }

    fun setScope(value: GlobalSearchScope) {
        _uiState.update { it.copy(scope = value) }
        recompute()
    }

    fun refreshPending() {
        if (_uiState.value.loadingPending) return
        viewModelScope.launch {
            val generation = requestGeneration
            _uiState.update { it.copy(loadingPending = true, message = null) }
            repository.fetchPending()
                .onSuccess { expenses ->
                    if (requestGeneration != generation) return@onSuccess
                    pendingCache = expenses
                    _uiState.update {
                        it.copy(
                            loadingPending = false,
                            pendingLoaded = true,
                            message = null,
                        )
                    }
                    recompute()
                }
                .onFailure { error ->
                    if (requestGeneration != generation) return@onFailure
                    _uiState.update {
                        it.copy(
                            loadingPending = false,
                            pendingLoaded = true,
                            message = error.message ?: "待确认账单暂时加载不了，先看本机账本。",
                        )
                    }
                    recompute()
                }
        }
    }

    private fun recompute() {
        _uiState.update { state ->
            val term = state.query.trim()
            if (term.isBlank()) {
                return@update state.copy(
                    results = emptyList(),
                    pendingMatchCount = 0,
                    confirmedMatchCount = 0,
                )
            }

            val pendingMatches = pendingCache
                .mapNotNull { expense -> expense.toSearchResult(GlobalSearchResultKind.Pending, term) }
            val confirmedMatches = confirmedCache
                .mapNotNull { expense -> expense.toSearchResult(GlobalSearchResultKind.Confirmed, term) }
            val pending = pendingMatches.take(MAX_RESULTS_PER_BUCKET)
            val confirmed = confirmedMatches.take(MAX_RESULTS_PER_BUCKET)
            val scoped = when (state.scope) {
                GlobalSearchScope.All -> pending + confirmed
                GlobalSearchScope.Pending -> pending
                GlobalSearchScope.Confirmed -> confirmed
            }
            state.copy(
                results = scoped,
                pendingMatchCount = pendingMatches.size,
                confirmedMatchCount = confirmedMatches.size,
            )
        }
    }

    private fun Expense.toSearchResult(kind: GlobalSearchResultKind, term: String): GlobalSearchResultUi? {
        val match = searchMatch(term) ?: return null
        return GlobalSearchResultUi(
            kind = kind,
            expense = this,
            title = merchant?.takeIf { it.isNotBlank() } ?: category,
            matchedField = match.label,
        )
    }

    private fun Expense.searchMatch(term: String): SearchMatch? {
        val terms = term
            .lowercase()
            .split(Regex("\\s+"))
            .filter { it.isNotBlank() }
        if (terms.isEmpty()) return null
        val fields = listOf(
            SearchField("商家", merchant, 0),
            SearchField("分类", category, 1),
            SearchField("备注", note, 2),
            SearchField("标签", tags, 2),
            SearchField("来源", source, 3),
            SearchField("原文", rawText, 4),
        ).filter { !it.value.isNullOrBlank() }

        val matchesAllTerms = terms.all { termPart ->
            fields.any { field -> field.value.orEmpty().lowercase().contains(termPart) }
        }
        if (!matchesAllTerms) return null
        return fields
            .filter { field ->
                terms.any { termPart -> field.value.orEmpty().lowercase().contains(termPart) }
            }
            .minByOrNull { it.score }
            ?.let { SearchMatch(it.label) }
    }

    private data class SearchField(
        val label: String,
        val value: String?,
        val score: Int,
    )

    private data class SearchMatch(val label: String)

    private companion object {
        const val MAX_QUERY_LENGTH = 80
        const val MAX_RESULTS_PER_BUCKET = 20
    }
}
