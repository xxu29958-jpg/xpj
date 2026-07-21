package com.ticketbox.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ticketbox.ui.screens.inbox.InboxProcessingActions
import com.ticketbox.ui.screens.inbox.InboxProcessingScreen
import com.ticketbox.viewmodel.BackgroundTasksViewModel
import com.ticketbox.viewmodel.backgroundTasksViewModelFactory

@Composable
internal fun InboxProcessingRoute(
    screenFactory: MainScreenFactory,
    onBack: () -> Unit,
) {
    val viewModel: BackgroundTasksViewModel = viewModel(
        factory = backgroundTasksViewModelFactory(screenFactory.repository),
    )
    val state by viewModel.uiState.collectAsStateWithLifecycle()

    LaunchedEffect(Unit) {
        viewModel.refresh()
    }

    InboxProcessingScreen(
        state = state,
        actions = InboxProcessingActions(
            onBack = onBack,
            onRefresh = viewModel::refresh,
            onCancel = viewModel::cancel,
        ),
    )
}
