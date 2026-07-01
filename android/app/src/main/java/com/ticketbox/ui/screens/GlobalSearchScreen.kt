package com.ticketbox.ui.screens

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppContentCard
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppScrollableContent
import com.ticketbox.ui.components.AppSecondaryPageHeader
import com.ticketbox.ui.components.AppSegmentedControl
import com.ticketbox.ui.components.AppSegmentedItem
import com.ticketbox.ui.components.MonthPickerSheet
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTypography
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.viewmodel.GlobalSearchScope
import com.ticketbox.viewmodel.GlobalSearchUiState

/**
 * Bundles the global-search user actions so the screen + its control card stay
 * within the parameter budget (mirrors SyncStatusActions / ExpenseEditActionBarActions).
 */
data class GlobalSearchActionsUi(
    val onQueryChange: (String) -> Unit,
    val onScopeChange: (GlobalSearchScope) -> Unit,
    val onCategoryChange: (String) -> Unit,
    val onMonthChange: (String) -> Unit,
    val onCommitSearch: () -> Unit,
    val onApplyRecentSearch: (String) -> Unit,
    val onClearRecentSearches: () -> Unit,
    val onRefreshPending: () -> Unit,
    val onOpenExpense: (Long) -> Unit,
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun GlobalSearchScreen(
    state: GlobalSearchUiState,
    actions: GlobalSearchActionsUi,
    onBack: (() -> Unit)? = null,
) {
    var showMonthPicker by rememberSaveable { mutableStateOf(false) }

    if (onBack != null) {
        BackHandler(onBack = onBack)
    }

    if (showMonthPicker) {
        ModalBottomSheet(onDismissRequest = { showMonthPicker = false }) {
            MonthPickerSheet(
                months = state.availableMonths,
                selectedMonth = state.monthFilter,
                description = stringResource(R.string.global_search_filter_month_picker_description),
                onSelectMonth = { month ->
                    actions.onMonthChange(month)
                    showMonthPicker = false
                },
            )
        }
    }

    AppScrollableContent(
        role = AppPageRole.Ledger,
        isRefreshing = state.loadingPending,
        onRefresh = actions.onRefreshPending,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
    ) {
        item {
            SearchHeader(onBack = onBack)
        }
        item {
            SearchControlCard(
                state = state,
                actions = actions,
                onOpenMonthPicker = { showMonthPicker = true },
            )
        }
        state.message?.let { message ->
            item { SearchMessageCard(message = message) }
        }
        searchBody(state = state, actions = actions)
    }
}

@Composable
private fun SearchHeader(onBack: (() -> Unit)?) {
    AppSecondaryPageHeader(
        title = stringResource(R.string.global_search_header_title),
        subtitle = stringResource(R.string.global_search_header_subtitle),
        backText = stringResource(R.string.global_search_back),
        onBack = onBack,
    )
}

private fun LazyListScope.searchBody(
    state: GlobalSearchUiState,
    actions: GlobalSearchActionsUi,
) {
    when {
        state.query.isBlank() && !state.hasActiveFilters -> item {
            SearchBlankState(
                recentSearches = state.recentSearches,
                onApplyRecentSearch = actions.onApplyRecentSearch,
                onClearRecentSearches = actions.onClearRecentSearches,
            )
        }
        state.results.isEmpty() -> item {
            SearchEmptyCard(
                title = stringResource(R.string.global_search_empty_nomatch_title),
                subtitle = stringResource(R.string.global_search_empty_nomatch_subtitle),
            )
        }
        else -> {
            items(
                items = state.results,
                key = { result -> "${result.kind}-${result.expense.id}" },
            ) { result ->
                SearchResultCard(
                    result = result,
                    onClick = { actions.onOpenExpense(result.expense.id) },
                )
            }
            if (state.truncated) {
                item { SearchTruncatedFooter(limit = state.resultLimit) }
            }
        }
    }
}

@Composable
private fun SearchControlCard(
    state: GlobalSearchUiState,
    actions: GlobalSearchActionsUi,
    onOpenMonthPicker: () -> Unit,
) {
    AppContentCard(
        contentPadding = PaddingValues(AppSpacing.cardPaddingSmall),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        OutlinedTextField(
            value = state.query,
            onValueChange = actions.onQueryChange,
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
            leadingIcon = {
                Icon(
                    imageVector = Icons.Filled.Search,
                    contentDescription = null,
                    modifier = Modifier.size(SearchLayout.IconSize),
                )
            },
            trailingIcon = {
                if (state.query.isNotBlank()) {
                    IconButton(onClick = { actions.onQueryChange("") }) {
                        Icon(
                            Icons.Filled.Close,
                            contentDescription = stringResource(R.string.global_search_clear_action),
                        )
                    }
                }
            },
            label = { Text(stringResource(R.string.global_search_field_label)) },
            placeholder = { Text(stringResource(R.string.global_search_field_placeholder)) },
            supportingText = { Text(stringResource(R.string.global_search_filter_amount_hint)) },
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
            keyboardActions = KeyboardActions(onSearch = { actions.onCommitSearch() }),
        )
        SearchFilterChips(
            state = state,
            onCategoryChange = actions.onCategoryChange,
            onOpenMonthPicker = onOpenMonthPicker,
        )
        SearchScopeSelector(state = state, onScopeChange = actions.onScopeChange)
    }
}

@Composable
private fun SearchScopeSelector(
    state: GlobalSearchUiState,
    onScopeChange: (GlobalSearchScope) -> Unit,
) {
    AppSegmentedControl(
        options = listOf(
            AppSegmentedItem(
                GlobalSearchScope.All,
                stringResource(
                    R.string.global_search_scope_all,
                    state.pendingMatchCount + state.confirmedMatchCount,
                ),
            ),
            AppSegmentedItem(
                GlobalSearchScope.Pending,
                stringResource(R.string.global_search_scope_pending, state.pendingMatchCount),
            ),
            AppSegmentedItem(
                GlobalSearchScope.Confirmed,
                stringResource(R.string.global_search_scope_confirmed, state.confirmedMatchCount),
            ),
        ),
        selectedValue = state.scope,
        onValueChange = onScopeChange,
    )
}

/**
 * One scrollable row of filter chips below the search box: the month chip (opens
 * the shared [MonthPickerSheet]) followed by category chips. Mirrors the ledger
 * inline filter row so the two surfaces share one chip idiom + token palette.
 */
@Composable
private fun SearchFilterChips(
    state: GlobalSearchUiState,
    onCategoryChange: (String) -> Unit,
    onOpenMonthPicker: () -> Unit,
) {
    LazyRow(horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap)) {
        item {
            AppFilterChip(
                selected = state.monthFilter.isNotBlank(),
                onClick = onOpenMonthPicker,
                label = state.monthFilter.takeIf { it.isNotBlank() }
                    ?.let { displayMonthLabel(it) }
                    ?: stringResource(R.string.global_search_filter_month_all),
                trailingIcon = {
                    Icon(
                        imageVector = Icons.Filled.ExpandMore,
                        contentDescription = stringResource(R.string.global_search_filter_month_picker_description),
                        modifier = Modifier.size(FilterChipDefaults.IconSize),
                    )
                },
            )
        }
        item {
            SelectableFilterChip(
                selected = state.categoryFilter.isBlank(),
                label = stringResource(R.string.global_search_filter_category_all),
                onClick = { onCategoryChange("") },
            )
        }
        items(state.availableCategories, key = { it }) { category ->
            SelectableFilterChip(
                selected = state.categoryFilter == category,
                label = category,
                onClick = { onCategoryChange(category) },
            )
        }
    }
}

@Composable
private fun SearchMessageCard(message: UiText) {
    val tone = LocalStateTokens.current.warn
    AppContentCard(
        contentPadding = PaddingValues(AppSpacing.cardPaddingSmall),
    ) {
        Text(
            text = message.asString(),
            color = tone.fg,
            style = MaterialTheme.typography.bodyMedium,
        )
    }
}

/**
 * Blank-query landing: the matching hint plus, when present, clickable recent
 * searches that refill the box. The "清除" affordance wipes the local history.
 */
@Composable
private fun SearchBlankState(
    recentSearches: List<String>,
    onApplyRecentSearch: (String) -> Unit,
    onClearRecentSearches: () -> Unit,
) {
    AppContentCard(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
            Text(
                text = stringResource(R.string.global_search_empty_blank_title),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = AppTypography.cardTitle.weight,
            )
            Text(
                text = stringResource(R.string.global_search_empty_blank_subtitle),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodyMedium,
            )
        }
        if (recentSearches.isNotEmpty()) {
            RecentSearchSection(
                recentSearches = recentSearches,
                onApplyRecentSearch = onApplyRecentSearch,
                onClearRecentSearches = onClearRecentSearches,
            )
        }
    }
}

@Composable
private fun RecentSearchSection(
    recentSearches: List<String>,
    onApplyRecentSearch: (String) -> Unit,
    onClearRecentSearches: () -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = stringResource(R.string.global_search_recent_title),
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Text(
                text = stringResource(R.string.global_search_recent_clear),
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.primary,
                modifier = Modifier.clickable(onClick = onClearRecentSearches),
            )
        }
        LazyRow(horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap)) {
            items(recentSearches, key = { it }) { query ->
                SelectableFilterChip(
                    selected = false,
                    label = query,
                    onClick = { onApplyRecentSearch(query) },
                )
            }
        }
    }
}

@Composable
private fun SearchEmptyCard(
    title: String,
    subtitle: String,
) {
    AppContentCard {
        Text(
            text = title,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = AppTypography.cardTitle.weight,
        )
        Text(
            text = subtitle,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodyMedium,
        )
    }
}

@Composable
private fun SearchTruncatedFooter(limit: Int) {
    Text(
        text = stringResource(R.string.global_search_result_truncated, limit),
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        style = MaterialTheme.typography.bodySmall,
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = AppSpacing.smallGap, vertical = AppSpacing.miniGap),
    )
}

private object SearchLayout {
    val IconSize: Dp = 20.dp
}
