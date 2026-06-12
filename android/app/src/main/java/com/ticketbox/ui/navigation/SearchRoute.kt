package com.ticketbox.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavHostController
import com.ticketbox.ui.screens.GlobalSearchActionsUi
import com.ticketbox.ui.screens.GlobalSearchScreen
import com.ticketbox.viewmodel.GlobalSearchViewModel

@Composable
internal fun SearchRoute(
    navController: NavHostController,
    screenFactory: MainScreenFactory,
) {
    val viewModel: GlobalSearchViewModel = viewModel(factory = screenFactory.repositoryViewModelFactory)
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    GlobalSearchScreen(
        state = state,
        actions = GlobalSearchActionsUi(
            onQueryChange = viewModel::setQuery,
            onScopeChange = viewModel::setScope,
            onCategoryChange = viewModel::setCategoryFilter,
            onMonthChange = viewModel::setMonthFilter,
            onCommitSearch = viewModel::commitSearch,
            onApplyRecentSearch = viewModel::applyRecentSearch,
            onClearRecentSearches = viewModel::clearRecentSearches,
            onRefreshPending = viewModel::refreshPending,
            onOpenExpense = navController::openExpense,
        ),
    )
}
