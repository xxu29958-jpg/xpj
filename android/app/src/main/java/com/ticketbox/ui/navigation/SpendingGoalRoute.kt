package com.ticketbox.ui.navigation

import androidx.compose.runtime.Composable
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ticketbox.ui.screens.CreateSpendingGoalScreen
import com.ticketbox.viewmodel.CreateSpendingGoalViewModel
import com.ticketbox.viewmodel.createSpendingGoalViewModelFactory

private const val CreateSpendingGoalViewModelKey = "create-spending-goal"

@Composable
internal fun CreateSpendingGoalRoute(
    screenFactory: MainScreenFactory,
    onBack: () -> Unit,
    onCreated: () -> Unit,
) {
    val viewModel: CreateSpendingGoalViewModel = viewModel(
        key = CreateSpendingGoalViewModelKey,
        factory = createSpendingGoalViewModelFactory(screenFactory.reportsRepository),
    )
    CreateSpendingGoalScreen(
        viewModel = viewModel,
        onBack = onBack,
        onCreated = onCreated,
    )
}
