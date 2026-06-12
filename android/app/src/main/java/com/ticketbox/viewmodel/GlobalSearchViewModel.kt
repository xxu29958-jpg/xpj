package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.GlobalSearchActions
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.RECENT_SEARCH_LIMIT
import com.ticketbox.domain.model.UiText
import com.ticketbox.domain.model.appendRecentSearch
import com.ticketbox.domain.model.expenseLedgerMonth
import com.ticketbox.domain.model.expenseMatchesAmountCents
import com.ticketbox.domain.model.parseSearchAmountCents
import com.ticketbox.domain.model.searchableCategories
import com.ticketbox.domain.model.searchableMonths
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
    val matchedField: UiText,
)

data class GlobalSearchUiState(
    val query: String = "",
    val scope: GlobalSearchScope = GlobalSearchScope.All,
    // Active chip filters, AND-combined with the text/amount term. Blank = off.
    val categoryFilter: String = "",
    val monthFilter: String = "",
    // Derived from the local caches so the chips only offer real categories/months.
    val availableCategories: List<String> = emptyList(),
    val availableMonths: List<String> = emptyList(),
    // Recent committed queries, most-recent-first (blank-query state only).
    val recentSearches: List<String> = emptyList(),
    val results: List<GlobalSearchResultUi> = emptyList(),
    val pendingMatchCount: Int = 0,
    val confirmedMatchCount: Int = 0,
    // True when either bucket was capped at [resultLimit] — drives the
    // "仅显示前 N 条" footer so the user knows to narrow with a filter.
    val truncated: Boolean = false,
    val resultLimit: Int = MAX_RESULTS_PER_BUCKET,
    val loadingPending: Boolean = false,
    val pendingLoaded: Boolean = false,
    val message: UiText? = null,
) {
    val hasActiveFilters: Boolean
        get() = categoryFilter.isNotBlank() || monthFilter.isNotBlank()
}

class GlobalSearchViewModel(
    private val repository: GlobalSearchActions,
) : ViewModel() {
    private val _uiState = MutableStateFlow(
        GlobalSearchUiState(recentSearches = repository.recentSearches()),
    )
    val uiState: StateFlow<GlobalSearchUiState> = _uiState.asStateFlow()

    private var pendingCache: List<Expense> = emptyList()
    private var confirmedCache: List<Expense> = emptyList()
    private var requestGeneration = 0

    init {
        viewModelScope.launch {
            repository.observeConfirmed().collect { expenses ->
                confirmedCache = expenses
                refreshFacets()
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
                            // A ledger switch invalidates the cached facets and
                            // any category/month chip that no longer applies.
                            categoryFilter = "",
                            monthFilter = "",
                            availableCategories = emptyList(),
                            availableMonths = emptyList(),
                            results = emptyList(),
                            pendingMatchCount = 0,
                            confirmedMatchCount = 0,
                            truncated = false,
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

    fun setCategoryFilter(value: String) {
        _uiState.update { it.copy(categoryFilter = value) }
        recompute()
    }

    fun setMonthFilter(value: String) {
        _uiState.update { it.copy(monthFilter = value) }
        recompute()
    }

    /** Remember the current query in recent history (call on IME "search" /
     *  explicit submit). Pure dedup/cap lives in [appendRecentSearch]. */
    fun commitSearch() {
        val query = _uiState.value.query.trim()
        if (query.isBlank()) return
        val updated = appendRecentSearch(_uiState.value.recentSearches, query, RECENT_SEARCH_LIMIT)
        if (updated == _uiState.value.recentSearches) return
        repository.saveRecentSearches(updated)
        _uiState.update { it.copy(recentSearches = updated) }
    }

    /** Refill the box from a recent-search chip and run the search. */
    fun applyRecentSearch(query: String) {
        _uiState.update { it.copy(query = query.take(MAX_QUERY_LENGTH)) }
        recompute()
    }

    fun clearRecentSearches() {
        repository.saveRecentSearches(emptyList())
        _uiState.update { it.copy(recentSearches = emptyList()) }
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
                    refreshFacets()
                    recompute()
                }
                .onFailure { error ->
                    if (requestGeneration != generation) return@onFailure
                    _uiState.update {
                        it.copy(
                            loadingPending = false,
                            pendingLoaded = true,
                            message = error.toUiText(R.string.global_search_pending_load_failed),
                        )
                    }
                    recompute()
                }
        }
    }

    private fun refreshFacets() {
        val all = pendingCache + confirmedCache
        val categories = searchableCategories(all)
        val months = searchableMonths(all)
        _uiState.update { state ->
            state.copy(
                availableCategories = categories,
                availableMonths = months,
                // Drop a stale chip selection that the new caches no longer offer.
                categoryFilter = state.categoryFilter.takeIf { it.isBlank() || it in categories }.orEmpty(),
                monthFilter = state.monthFilter.takeIf { it.isBlank() || it in months }.orEmpty(),
            )
        }
    }

    private fun recompute() {
        _uiState.update { state ->
            val term = state.query.trim()
            if (term.isBlank() && !state.hasActiveFilters) {
                return@update state.copy(
                    results = emptyList(),
                    pendingMatchCount = 0,
                    confirmedMatchCount = 0,
                    truncated = false,
                )
            }
            val criteria = SearchCriteria(
                term = term,
                amountCents = parseSearchAmountCents(term),
                category = state.categoryFilter,
                month = state.monthFilter,
            )
            val pendingMatches = pendingCache
                .mapNotNull { it.toSearchResult(GlobalSearchResultKind.Pending, criteria) }
            val confirmedMatches = confirmedCache
                .mapNotNull { it.toSearchResult(GlobalSearchResultKind.Confirmed, criteria) }
            val scoped = sliceForScope(pendingMatches, confirmedMatches, state.scope)
            state.copy(
                results = scoped.results,
                pendingMatchCount = pendingMatches.size,
                confirmedMatchCount = confirmedMatches.size,
                truncated = scoped.truncated,
            )
        }
    }

    /** Apply the scope segment + per-bucket cap, reporting whether anything was
     *  cut so the screen can show the "仅显示前 N 条" footer. */

    private companion object {
        const val MAX_QUERY_LENGTH = 80
    }
}

// Pure search mechanics, file-level so the class stays inside the detekt
// functions-per-class budget; nothing here touches ViewModel state.
private fun sliceForScope(
    pendingMatches: List<GlobalSearchResultUi>,
    confirmedMatches: List<GlobalSearchResultUi>,
    scope: GlobalSearchScope,
): ScopedResults {
    val pending = pendingMatches.take(MAX_RESULTS_PER_BUCKET)
    val confirmed = confirmedMatches.take(MAX_RESULTS_PER_BUCKET)
    val pendingCut = pendingMatches.size > MAX_RESULTS_PER_BUCKET
    val confirmedCut = confirmedMatches.size > MAX_RESULTS_PER_BUCKET
    return when (scope) {
        GlobalSearchScope.All -> ScopedResults(pending + confirmed, pendingCut || confirmedCut)
        GlobalSearchScope.Pending -> ScopedResults(pending, pendingCut)
        GlobalSearchScope.Confirmed -> ScopedResults(confirmed, confirmedCut)
    }
}

private fun Expense.toSearchResult(
    kind: GlobalSearchResultKind,
    criteria: SearchCriteria,
): GlobalSearchResultUi? {
    if (!criteria.category.isBlank() && category != criteria.category) return null
    if (!criteria.month.isBlank() && expenseLedgerMonth(this) != criteria.month) return null
    val match = matchTerm(criteria) ?: return null
    return GlobalSearchResultUi(
        kind = kind,
        expense = this,
        title = merchant?.takeIf { it.isNotBlank() } ?: category,
        matchedField = match,
    )
}

/** Resolve which field (or the amount) the [criteria] hit, or null for no
 *  match. A blank term with active filters matches every filtered row. */
private fun Expense.matchTerm(criteria: SearchCriteria): UiText? {
    if (criteria.term.isBlank()) return UiText.res(R.string.global_search_field_all)
    val amountHit = criteria.amountCents != null && expenseMatchesAmountCents(this, criteria.amountCents)
    val textMatch = textSearchMatch(criteria.term)
    return when {
        textMatch != null -> textMatch
        amountHit -> UiText.res(R.string.global_search_field_amount)
        else -> null
    }
}

private fun Expense.textSearchMatch(term: String): UiText? {
    val terms = term
        .lowercase()
        .split(Regex("\\s+"))
        .filter { it.isNotBlank() }
    if (terms.isEmpty()) return null
    val fields = listOf(
        SearchField(UiText.res(R.string.global_search_field_merchant), merchant, 0),
        SearchField(UiText.res(R.string.global_search_field_category), category, 1),
        SearchField(UiText.res(R.string.global_search_field_note), note, 2),
        SearchField(UiText.res(R.string.global_search_field_tags), tags, 2),
        SearchField(UiText.res(R.string.global_search_field_source), source, 3),
        SearchField(UiText.res(R.string.global_search_field_raw_text), rawText, 4),
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
        ?.label
}

private data class SearchCriteria(
    val term: String,
    val amountCents: Long?,
    val category: String,
    val month: String,
)

private data class ScopedResults(
    val results: List<GlobalSearchResultUi>,
    val truncated: Boolean,
)

private data class SearchField(
    val label: UiText,
    val value: String?,
    val score: Int,
)

// File-level so both the VM and the UiState default parameter can read it
// (a private companion member is invisible to the sibling data class).
private const val MAX_RESULTS_PER_BUCKET = 20
