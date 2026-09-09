package com.ticketbox.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ticketbox.ui.screens.CreateSpendingGoalScreen
import com.ticketbox.ui.screens.plan.SpendingGoalDetailScreen
import com.ticketbox.ui.screens.plan.SpendingGoalsScreen
import com.ticketbox.ui.screens.plan.SpendingGoalsScreenActions
import com.ticketbox.viewmodel.CreateSpendingGoalViewModel
import com.ticketbox.viewmodel.SpendingGoalDetailViewModel
import com.ticketbox.viewmodel.SpendingGoalDetailUiState
import com.ticketbox.viewmodel.SpendingGoalsViewModel
import com.ticketbox.viewmodel.createSpendingGoalViewModelFactory
import com.ticketbox.viewmodel.spendingGoalDetailViewModelFactory
import com.ticketbox.viewmodel.spendingGoalsViewModelFactory

private const val SpendingGoalsViewModelKey = "spending-goals"
private const val SpendingGoalDetailViewModelKey = "spending-goal-detail"
private const val CreateSpendingGoalViewModelKey = "create-spending-goal"

private enum class SpendingGoalPage {
    List,
    Create,
    Detail,
}

private data class SpendingGoalRouteModels(
    val list: SpendingGoalsViewModel,
    val detail: SpendingGoalDetailViewModel,
    val create: CreateSpendingGoalViewModel,
)

@Composable
internal fun SpendingGoalsRoute(
    screenFactory: MainScreenFactory,
    onBack: () -> Unit,
    originalCreationId: Long? = null,
    originalGoalPublicId: String? = null,
) {
    SpendingGoalRouteContent(
        models = SpendingGoalRouteModels(
            list = viewModel(
                key = SpendingGoalsViewModelKey,
                factory = spendingGoalsViewModelFactory(screenFactory.reportsRepository, screenFactory.goalEditRepository),
            ),
            detail = viewModel(
                key = SpendingGoalDetailViewModelKey,
                factory = spendingGoalDetailViewModelFactory(screenFactory.reportsRepository, screenFactory.goalEditRepository),
            ),
            create = viewModel(
                key = CreateSpendingGoalViewModelKey,
                factory = createSpendingGoalViewModelFactory(screenFactory.goalEditRepository),
            ),
        ),
        onBack = onBack,
        originalCreationId = originalCreationId,
        originalGoalPublicId = originalGoalPublicId,
    )
}

@Composable
private fun SpendingGoalRouteContent(
    models: SpendingGoalRouteModels,
    onBack: () -> Unit,
    originalCreationId: Long?,
    originalGoalPublicId: String?,
) {
    var page by rememberSaveable(originalCreationId, originalGoalPublicId) { mutableStateOf(when {
        originalCreationId != null -> SpendingGoalPage.Create
        originalGoalPublicId != null -> SpendingGoalPage.Detail
        else -> SpendingGoalPage.List
    }) }
    var creationToOpen by rememberSaveable(originalCreationId) { mutableStateOf(originalCreationId) }
    var detailPublicId by rememberSaveable(originalGoalPublicId) { mutableStateOf(originalGoalPublicId) }
    var createMonth by rememberSaveable { mutableStateOf(models.list.state.value.month) }
    val detailState by models.detail.state.collectAsStateWithLifecycle()

    LaunchedEffect(page, detailPublicId) {
        if (page == SpendingGoalPage.Detail) {
            detailPublicId?.let(models.detail::load)
        }
    }
    SpendingGoalDetailResultEffect(detailState, models.list::refresh) {
        detailPublicId = null
        page = SpendingGoalPage.List
    }

    when (page) {
        SpendingGoalPage.List -> SpendingGoalsScreen(
            viewModel = models.list,
            actions = SpendingGoalsScreenActions(
                onBack = onBack,
                onCreate = {
                    creationToOpen = null
                    createMonth = models.list.state.value.month
                    page = SpendingGoalPage.Create
                },
                onOpenGoal = {
                    detailPublicId = it
                    page = SpendingGoalPage.Detail
                },
            ),
        )
        SpendingGoalPage.Create -> CreateSpendingGoalScreen(
            viewModel = models.create,
            initialMonth = createMonth,
            originalId = creationToOpen,
            onBack = { creationToOpen = null; page = SpendingGoalPage.List },
            onCreated = {
                creationToOpen = null
                models.list.refresh()
                page = SpendingGoalPage.List
            },
        )
        SpendingGoalPage.Detail -> SpendingGoalDetailScreen(
            viewModel = models.detail,
            onBack = {
                detailPublicId = null
                page = SpendingGoalPage.List
            },
        )
    }
}

@Composable
private fun SpendingGoalDetailResultEffect(state: SpendingGoalDetailUiState, refreshList: () -> Unit, onArchived: () -> Unit) {
    LaunchedEffect(state.mutationRevision, state.archiveCompleted) {
        if (state.mutationRevision > 0) {
            refreshList()
            if (state.archiveCompleted) onArchived()
        }
    }
}
