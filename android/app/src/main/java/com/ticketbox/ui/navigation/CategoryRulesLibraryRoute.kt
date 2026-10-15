package com.ticketbox.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavGraphBuilder
import androidx.navigation.NavHostController
import androidx.navigation.compose.composable
import androidx.navigation.NavBackStackEntry
import androidx.navigation.NavType
import androidx.navigation.navArgument
import com.ticketbox.ui.screens.settings.CategoryRulesApplicationActions
import com.ticketbox.ui.screens.settings.CategoryRulesApplicationState
import com.ticketbox.ui.screens.settings.CategoryRulesInteractionState
import com.ticketbox.ui.screens.settings.CategoryRulesRuleActions
import com.ticketbox.ui.screens.settings.CategoryRulesRuleListState
import com.ticketbox.ui.screens.settings.CategoryRulesScreen
import com.ticketbox.ui.screens.settings.CategoryRulesScreenActions
import com.ticketbox.ui.screens.settings.CategoryRulesScreenState
import com.ticketbox.ui.screens.settings.CategoryRulesStatusState
import com.ticketbox.ui.screens.settings.CategoryRulesUndoActions
import com.ticketbox.viewmodel.CategoryRulesViewModel

@Composable
private fun CategoryRulesLibraryRoute(
    navController: NavHostController,
    screenFactory: MainScreenFactory,
    onVocabularyChanged: () -> Unit,
    onTransactionRowsChanged: () -> Unit,
    entry: NavBackStackEntry,
) {
    val originalSubmissionId = entry.arguments?.getString("submission")?.toLongOrNull()
    val originalRuleId = entry.arguments?.getString("rule")?.toLongOrNull()
    val viewModel: CategoryRulesViewModel = viewModel(
        key = transactionsLibraryViewModelKey("category-rules", screenFactory.ledgerRepository.activeLedgerId()),
        factory = screenFactory.categoryRulesViewModelFactory,
    )
    LaunchedEffect(viewModel, originalSubmissionId) { originalSubmissionId?.let(viewModel::openSubmission) }
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    val definitions by viewModel.definitions.state.collectAsStateWithLifecycle()
    ReportSuccessfulLibraryWrites(viewModel.uiState, onVocabularyChanged) { it.changedRevision }
    ReportSuccessfulLibraryWrites(viewModel.uiState, onTransactionRowsChanged) { it.applicationRevision }
    CategoryRulesScreen(
        state = CategoryRulesScreenState(
            rules = CategoryRulesRuleListState(rules = state.categoryRules, loading = state.categoryRulesLoading,
                loadFailed = state.categoryRulesLoadFailed,
            ),
            interaction = CategoryRulesInteractionState(busy = state.busy, readOnly = !state.canModify),
            status = CategoryRulesStatusState(state.message, state.messageTone),
            applications = CategoryRulesApplicationState(
                history = state.ruleApplications,
                loading = state.ruleApplicationsLoading,
                confirmedPreview = state.confirmedRulesPreview,
                loadFailed = state.ruleApplicationsLoadFailed,
                reason = state.applicationReason,
                rollback = state.rollback,
            ),
            undoableRule = state.undoableRule,
            submissions = state.pendingSubmissions, selectedSubmissionId = state.selectedSubmissionId,
            applicationSubmissions = state.pendingApplications,
            submittedRevision = state.submittedRevision, binding = state.binding,
            definitions = definitions,
        ),
        actions = CategoryRulesScreenActions(
            onBack = navController::popBackStack,
            definitions = com.ticketbox.ui.screens.settings.CategoryRuleDefinitionActions(
                viewModel.definitions::begin, viewModel.definitions::open, viewModel.definitions::change,
                viewModel.definitions::submit, viewModel.definitions::close, viewModel.definitions::reviewBinding,
                viewModel.definitions::reload),
            rules = CategoryRulesRuleActions(
                onToggle = viewModel::toggleCategoryRule,
                onDelete = viewModel::deleteCategoryRule,
                onRecoverSubmission = viewModel::recoverSubmission,
                onReload = { viewModel.loadCategoryRules() },
            ),
            applications = viewModel.applicationActions(),
            undo = CategoryRulesUndoActions(
                onUndoDelete = viewModel::undoDelete,
                onDismiss = viewModel::dismissUndo,
            ),
        ),
        chrome = libraryManagementChrome(navController.previousBackStackEntry?.destination?.route == TRANSACTIONS_LIBRARY_CATEGORIES_ROUTE),
        initialRuleId = originalRuleId,
    )
}

private fun CategoryRulesViewModel.applicationActions() = CategoryRulesApplicationActions(
    onPreviewApplyConfirmedRules = ::previewApplyConfirmedRules,
    onConfirmApplyConfirmedRules = ::confirmApplyConfirmedRules,
    onRollbackRuleApplication = ::openRollback,
    onReload = { loadRuleApplications() },
    onRecover = ::recoverApplication,
    onReasonChange = ::changeApplicationReason,
    rollback = com.ticketbox.ui.screens.settings.CategoryRuleRollbackActions(
        ::dismissRollback, ::confirmRollback, ::refreshRollbackPreview, ::changeRollbackReason),
)

internal fun NavGraphBuilder.categoryRulesDestination(
    navController: NavHostController,
    screenFactory: MainScreenFactory,
    onVocabularyChanged: () -> Unit,
    onTransactionRowsChanged: () -> Unit,
) {
    composable("$TRANSACTIONS_LIBRARY_RULES_ROUTE?submission={submission}&rule={rule}", arguments = listOf(
        navArgument("submission") { type = NavType.StringType; nullable = true; defaultValue = null },
        navArgument("rule") { type = NavType.StringType; nullable = true; defaultValue = null },
    )) { entry ->
        CategoryRulesLibraryRoute(
            navController = navController,
            screenFactory = screenFactory,
            onVocabularyChanged = onVocabularyChanged,
            onTransactionRowsChanged = onTransactionRowsChanged,
            entry = entry,
        )
    }
}
