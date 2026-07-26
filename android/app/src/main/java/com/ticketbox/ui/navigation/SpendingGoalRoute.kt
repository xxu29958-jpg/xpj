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
) {
    SpendingGoalRouteContent(
        models = SpendingGoalRouteModels(
            list = viewModel(
                key = SpendingGoalsViewModelKey,
                factory = spendingGoalsViewModelFactory(screenFactory.reportsRepository),
            ),
            detail = viewModel(
                key = SpendingGoalDetailViewModelKey,
                factory = spendingGoalDetailViewModelFactory(screenFactory.reportsRepository),
            ),
            create = viewModel(
                key = CreateSpendingGoalViewModelKey,
                factory = createSpendingGoalViewModelFactory(screenFactory.reportsRepository),
            ),
        ),
        onBack = onBack,
    )
}

@Composable
private fun SpendingGoalRouteContent(
    models: SpendingGoalRouteModels,
    onBack: () -> Unit,
) {
    var page by rememberSaveable { mutableStateOf(SpendingGoalPage.List) }
    var detailPublicId by rememberSaveable { mutableStateOf<String?>(null) }
    var createMonth by rememberSaveable { mutableStateOf(models.list.state.value.month) }
    val detailState by models.detail.state.collectAsStateWithLifecycle()

    LaunchedEffect(page, detailPublicId) {
        if (page == SpendingGoalPage.Detail) {
            detailPublicId?.let(models.detail::load)
        }
    }
    LaunchedEffect(detailState.mutationRevision, detailState.archiveCompleted) {
        if (detailState.mutationRevision > 0) {
            models.list.refresh()
            if (detailState.archiveCompleted) {
                detailPublicId = null
                page = SpendingGoalPage.List
            }
        }
    }

    when (page) {
        SpendingGoalPage.List -> SpendingGoalsScreen(
            viewModel = models.list,
            actions = SpendingGoalsScreenActions(
                onBack = onBack,
                onCreate = {
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
            onBack = { page = SpendingGoalPage.List },
            onCreated = {
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
