package com.ticketbox.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.ViewModelStoreOwner
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ticketbox.R
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

internal data class SpendingGoalRouteContext(
    val creationOwner: ViewModelStoreOwner,
    val originalCreationId: Long? = null,
    val originalGoalPublicId: String? = null,
    val financialDataRevision: Int = 0,
    val backText: Int = R.string.spending_goal_detail_back,
    val returnToCaller: Boolean = false,
)

@Composable
internal fun SpendingGoalsRoute(
    screenFactory: MainScreenFactory,
    onBack: () -> Unit,
    context: SpendingGoalRouteContext,
) {
    SpendingGoalRouteContent(
        models = SpendingGoalRouteModels(
            list = viewModel(
                key = SpendingGoalsViewModelKey,
                factory = spendingGoalsViewModelFactory(screenFactory.reportsRepository, screenFactory.goalEditRepository,
                    screenFactory.repositories.ledgerCalendarRepository),
            ),
            detail = viewModel(
                key = SpendingGoalDetailViewModelKey,
                factory = spendingGoalDetailViewModelFactory(screenFactory.reportsRepository, screenFactory.goalEditRepository),
            ),
            create = viewModel(
                viewModelStoreOwner = context.creationOwner,
                key = CreateSpendingGoalViewModelKey,
                factory = createSpendingGoalViewModelFactory(screenFactory.goalEditRepository, screenFactory.repositories.ledgerCalendarRepository),
            ),
        ),
        onBack = onBack,
        context = context,
    )
}

@Composable
private fun SpendingGoalRouteContent(
    models: SpendingGoalRouteModels,
    onBack: () -> Unit,
    context: SpendingGoalRouteContext,
) {
    var page by rememberSaveable(context.originalCreationId, context.originalGoalPublicId) { mutableStateOf(when {
        context.originalCreationId != null -> SpendingGoalPage.Create
        context.originalGoalPublicId != null -> SpendingGoalPage.Detail
        else -> SpendingGoalPage.List
    }) }
    var creationToOpen by rememberSaveable(context.originalCreationId) { mutableStateOf(context.originalCreationId) }
    var detailPublicId by rememberSaveable(context.originalGoalPublicId) { mutableStateOf(context.originalGoalPublicId) }
    var createMonth by rememberSaveable { mutableStateOf(models.list.monthForNewGoal) }
    val detailState by models.detail.state.collectAsStateWithLifecycle()
    val closeDetail = {
        detailPublicId = null
        if (context.returnToCaller) onBack() else page = SpendingGoalPage.List
    }

    LaunchedEffect(context.financialDataRevision) {
        if (context.financialDataRevision > 0) models.list.refresh()
    }
    LaunchedEffect(page, detailPublicId, context.financialDataRevision, detailState.isEditing) {
        if (page == SpendingGoalPage.Detail && !detailState.isEditing) {
            detailPublicId?.let(models.detail::load)
        }
    }
    SpendingGoalDetailResultEffect(detailState, models, closeDetail)

    when (page) {
        SpendingGoalPage.List -> SpendingGoalsScreen(
            viewModel = models.list,
            hasRetainedDraft = models.create.state.collectAsStateWithLifecycle().value.hasDraft,
            actions = SpendingGoalsScreenActions(
                onBack = onBack,
                onCreate = {
                    creationToOpen = null
                    createMonth = models.list.monthForNewGoal
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
            backText = context.backText,
            onBack = closeDetail,
        )
    }
}

@Composable
private fun SpendingGoalDetailResultEffect(state: SpendingGoalDetailUiState, models: SpendingGoalRouteModels, onArchived: () -> Unit) {
    LaunchedEffect(state.mutationRevision, state.archiveCompleted) {
        if (state.mutationRevision > 0) {
            if (state.archiveCompleted) {
                models.detail.acceptedArchive?.let { (binding, archived) -> models.list.acceptArchived(binding, archived) }
                onArchived()
            }
            models.list.refresh()
        }
    }
}
