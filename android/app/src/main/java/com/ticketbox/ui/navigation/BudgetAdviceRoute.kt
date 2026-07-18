package com.ticketbox.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ticketbox.ui.screens.plan.BudgetAdviceScreen
import com.ticketbox.viewmodel.BudgetAdviceViewModel
import com.ticketbox.viewmodel.budgetAdviceViewModelFactory

@Composable
internal fun BudgetAdviceRoute(
    screenFactory: MainScreenFactory,
    onBack: () -> Unit,
) {
    val viewModel: BudgetAdviceViewModel = viewModel(
        factory = budgetAdviceViewModelFactory(screenFactory.budgetRepository),
    )
    val state by viewModel.uiState.collectAsStateWithLifecycle()

    BudgetAdviceScreen(
        state = state,
        onRequestAdvice = viewModel::requestAdvice,
        onBack = onBack,
    )
}
