package com.ticketbox.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavGraphBuilder
import androidx.navigation.NavBackStackEntry
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.navArgument
import androidx.navigation.compose.composable
import androidx.navigation.compose.navigation
import com.ticketbox.R
import com.ticketbox.ui.components.AppPageRole
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
import com.ticketbox.ui.screens.settings.ManagementPageChrome
import com.ticketbox.ui.screens.settings.MerchantAliasesAliasActions
import com.ticketbox.ui.screens.settings.MerchantAliasesCatalogActions
import com.ticketbox.ui.screens.settings.MerchantAliasesMergeSuggestionActions
import com.ticketbox.ui.screens.settings.MerchantAliasesScreen
import com.ticketbox.ui.screens.settings.MerchantAliasesScreenActions
import com.ticketbox.ui.screens.settings.MerchantAliasesScreenState
import com.ticketbox.ui.screens.settings.MerchantAliasesUndoActions
import com.ticketbox.ui.screens.settings.TagManagementScreen
import com.ticketbox.ui.screens.transactions.RecycleBinScreen
import com.ticketbox.ui.screens.transactions.TransactionsLibraryActions
import com.ticketbox.ui.screens.transactions.TransactionsLibraryScreen
import com.ticketbox.viewmodel.CategoryRulesViewModel
import com.ticketbox.viewmodel.MerchantAliasViewModel
import com.ticketbox.viewmodel.RecycleBinViewModel
import com.ticketbox.viewmodel.TagManagementViewModel
import com.ticketbox.viewmodel.recycleBinViewModelFactory
import com.ticketbox.viewmodel.tagManagementViewModelFactory
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.flow.map

internal const val TRANSACTIONS_LIBRARY_ROUTE = "product/transactions/library"
internal const val TRANSACTIONS_LIBRARY_OVERVIEW_ROUTE = "$TRANSACTIONS_LIBRARY_ROUTE/overview"
internal const val TRANSACTIONS_LIBRARY_CATEGORIES_ROUTE = "$TRANSACTIONS_LIBRARY_ROUTE/categories"
internal const val TRANSACTIONS_LIBRARY_MERCHANTS_ROUTE = "$TRANSACTIONS_LIBRARY_ROUTE/merchants"
internal const val TRANSACTIONS_LIBRARY_TAGS_ROUTE = "$TRANSACTIONS_LIBRARY_ROUTE/tags"
internal const val TRANSACTIONS_LIBRARY_RULES_ROUTE = "$TRANSACTIONS_LIBRARY_ROUTE/rules"
internal fun categoryRuleSubmissionRoute(id: Long): String = "$TRANSACTIONS_LIBRARY_RULES_ROUTE?submission=$id"
internal fun categoryRuleEditRoute(id: Long): String = "$TRANSACTIONS_LIBRARY_RULES_ROUTE?rule=$id"
internal const val TRANSACTIONS_LIBRARY_RECYCLE_BIN_ROUTE = "$TRANSACTIONS_LIBRARY_ROUTE/recycle-bin"

/**
 * Transactions owns its vocabulary as an explicit subflow. Main navigation
 * only needs to install this graph and navigate to [TRANSACTIONS_LIBRARY_ROUTE].
 */
internal fun NavGraphBuilder.transactionsLibraryGraph(
    navController: NavHostController,
    screenFactory: MainScreenFactory,
    onVocabularyChanged: () -> Unit,
    onRestoreCompleted: () -> Unit,
    onTransactionRowsChanged: () -> Unit,
) {
    navigation(
        startDestination = TRANSACTIONS_LIBRARY_OVERVIEW_ROUTE,
        route = TRANSACTIONS_LIBRARY_ROUTE,
    ) {
        composable(TRANSACTIONS_LIBRARY_OVERVIEW_ROUTE) {
            TransactionsLibraryScreen(
                actions = TransactionsLibraryActions(
                    onBack = navController::popBackStack,
                    onOpenCategories = { navController.navigate(TRANSACTIONS_LIBRARY_CATEGORIES_ROUTE) },
                    onOpenMerchants = { navController.navigate(TRANSACTIONS_LIBRARY_MERCHANTS_ROUTE) },
                    onOpenTags = { navController.navigate(TRANSACTIONS_LIBRARY_TAGS_ROUTE) },
                    onOpenRules = { navController.navigate(TRANSACTIONS_LIBRARY_RULES_ROUTE) },
                    onOpenRecycleBin = { navController.navigate(TRANSACTIONS_LIBRARY_RECYCLE_BIN_ROUTE) },
                ),
            )
        }
        composable(TRANSACTIONS_LIBRARY_CATEGORIES_ROUTE) {
            CategoryDirectoryRoute(
                navController = navController,
                screenFactory = screenFactory,
                onVocabularyChanged = onVocabularyChanged,
            )
        }
        composable(TRANSACTIONS_LIBRARY_MERCHANTS_ROUTE) {
            MerchantDirectoryRoute(
                navController = navController,
                screenFactory = screenFactory,
                onVocabularyChanged = onVocabularyChanged,
            )
        }
        composable(TRANSACTIONS_LIBRARY_TAGS_ROUTE) {
            TagDirectoryRoute(
                navController = navController,
                screenFactory = screenFactory,
                onVocabularyChanged = onVocabularyChanged,
            )
        }
        categoryRulesDestination(navController, screenFactory, onVocabularyChanged, onTransactionRowsChanged)
        composable(TRANSACTIONS_LIBRARY_RECYCLE_BIN_ROUTE) {
            RecycleBinLibraryRoute(
                navController = navController,
                screenFactory = screenFactory,
                onRestoreCompleted = onRestoreCompleted,
                onTransactionRowsChanged = onTransactionRowsChanged,
            )
        }
    }
}

/**
 * Ledger-scoped ViewModel key for the library subflow: keying by active ledger
 * guarantees a fresh VM (fresh load) after a ledger switch instead of reusing
 * the previous ledger's state from the back stack.
 */
internal fun transactionsLibraryViewModelKey(prefix: String, ledgerId: String?): String =
    "$prefix-${ledgerId ?: "none"}"

@Composable
private fun RecycleBinLibraryRoute(
    navController: NavHostController,
    screenFactory: MainScreenFactory,
    onRestoreCompleted: () -> Unit,
    onTransactionRowsChanged: () -> Unit,
) {
    val viewModel: RecycleBinViewModel = viewModel(
        key = transactionsLibraryViewModelKey(
            "transactions-library-recycle-bin",
            screenFactory.ledgerRepository.activeLedgerId(),
        ),
        factory = recycleBinViewModelFactory(screenFactory.ledgerRepository),
    )
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    ReportSuccessfulLibraryWrites(viewModel.uiState, onRestoreCompleted) { it.changedRevision }
    ReportSuccessfulLibraryWrites(viewModel.uiState, onTransactionRowsChanged) {
        it.expenseRowsRestoredRevision
    }
    RecycleBinScreen(
        viewModel = viewModel,
        onBack = navController::popBackStack,
    )
}

@Composable
private fun TagDirectoryRoute(
    navController: NavHostController,
    screenFactory: MainScreenFactory,
    onVocabularyChanged: () -> Unit,
) {
    val viewModel: TagManagementViewModel = viewModel(
        key = transactionsLibraryViewModelKey(
            "tag-directory",
            screenFactory.ledgerRepository.activeLedgerId(),
        ),
        factory = tagManagementViewModelFactory(screenFactory.tagRepository),
    )
    TagManagementScreen(
        viewModel = viewModel,
        readOnly = !screenFactory.repository.canModifyLedger(),
        onBack = navController::popBackStack,
        onTagsChanged = onVocabularyChanged,
        chrome = libraryManagementChrome(),
    )
}

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
    ReportSuccessfulLibraryWrites(viewModel.uiState, onVocabularyChanged) { it.changedRevision }
    ReportSuccessfulLibraryWrites(viewModel.uiState, onTransactionRowsChanged) { it.applicationRevision }
    CategoryRulesScreen(
        state = CategoryRulesScreenState(
            rules = CategoryRulesRuleListState(
                rules = state.categoryRules,
                loading = state.categoryRulesLoading,
                loadFailed = state.categoryRulesLoadFailed,
            ),
            interaction = CategoryRulesInteractionState(
                busy = state.busy,
                readOnly = !state.canModify,
            ),
            status = CategoryRulesStatusState(state.message, state.messageTone),
            applications = CategoryRulesApplicationState(
                history = state.ruleApplications,
                loading = state.ruleApplicationsLoading,
                confirmedPreview = state.confirmedRulesPreview,
                loadFailed = state.ruleApplicationsLoadFailed,
            ),
            undoableRule = state.undoableRule,
            submissions = state.pendingSubmissions, selectedSubmissionId = state.selectedSubmissionId,
            submittedRevision = state.submittedRevision, binding = state.binding,
        ),
        actions = CategoryRulesScreenActions(
            onBack = navController::popBackStack,
            rules = CategoryRulesRuleActions(
                onCreate = viewModel::createCategoryRule,
                onUpdate = viewModel::updateCategoryRule,
                onToggle = viewModel::toggleCategoryRule,
                onDelete = viewModel::deleteCategoryRule,
                onRecoverSubmission = viewModel::recoverSubmission,
                onReload = { viewModel.loadCategoryRules() },
            ),
            applications = CategoryRulesApplicationActions(
                onPreviewApplyConfirmedRules = viewModel::previewApplyConfirmedRules,
                onConfirmApplyConfirmedRules = viewModel::confirmApplyConfirmedRules,
                onRollbackRuleApplication = viewModel::rollbackRuleApplication,
                onReload = { viewModel.loadRuleApplications() },
            ),
            undo = CategoryRulesUndoActions(
                onUndoDelete = viewModel::undoDelete,
                onDismiss = viewModel::dismissUndo,
            ),
        ),
        chrome = libraryManagementChrome(navController.previousBackStackEntry?.destination?.route == TRANSACTIONS_LIBRARY_CATEGORIES_ROUTE),
        initialRuleId = originalRuleId,
    )
}

@Composable
private fun MerchantDirectoryRoute(
    navController: NavHostController,
    screenFactory: MainScreenFactory,
    onVocabularyChanged: () -> Unit,
) {
    val viewModel: MerchantAliasViewModel = viewModel(
        key = transactionsLibraryViewModelKey(
            "merchant-directory",
            screenFactory.ledgerRepository.activeLedgerId(),
        ),
        factory = screenFactory.merchantAliasViewModelFactory,
    )
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    ReportSuccessfulLibraryWrites(viewModel.uiState, onVocabularyChanged) { it.changedRevision }
    MerchantAliasesScreen(
        state = MerchantAliasesScreenState(
            catalog = state.merchantCatalog,
            aliases = state.merchantAliases,
            aliasesLoadFailed = state.aliasesLoadFailed,
            busy = state.busy,
            readOnly = !screenFactory.repository.canModifyLedger(),
            message = state.message,
            messageTone = state.messageTone,
            undoableAlias = state.undoableAlias,
            mergeSuggestion = state.mergeSuggestion,
            editorCompletion = state.editorCompletion,
        ),
        actions = MerchantAliasesScreenActions(
            onBack = navController::popBackStack,
            onStartEditing = viewModel::dismissMessage,
            onReloadAliases = { viewModel.loadMerchantAliases() },
            catalog = MerchantAliasesCatalogActions(
                onCreate = viewModel::createMerchantCatalog,
                onRename = viewModel::renameMerchantCatalog,
                onToggle = viewModel::toggleMerchantCatalog,
                onMerge = viewModel::mergeMerchantCatalog,
                onDelete = viewModel::deleteMerchantCatalog,
            ),
            alias = MerchantAliasesAliasActions(
                onCreate = viewModel::createMerchantAlias,
                onToggle = viewModel::toggleMerchantAlias,
                onDelete = viewModel::deleteMerchantAlias,
            ),
            mergeSuggestion = MerchantAliasesMergeSuggestionActions(
                onDismiss = viewModel::consumeMergeSuggestion,
            ),
            undo = MerchantAliasesUndoActions(
                onUndoDelete = viewModel::undoDelete,
                onDismiss = viewModel::dismissUndo,
            ),
        ),
        chrome = libraryManagementChrome(),
    )
}

@Composable
private fun libraryManagementChrome(backToCategories: Boolean = false): ManagementPageChrome = ManagementPageChrome(
    role = AppPageRole.Ledger,
    backText = stringResource(if (backToCategories) R.string.category_directory_back else R.string.transactions_library_back_to_library),
)

@Composable
private fun <T> ReportSuccessfulLibraryWrites(
    state: StateFlow<T>,
    onChanged: () -> Unit,
    revision: (T) -> Int,
) {
    val currentOnChanged by rememberUpdatedState(onChanged)
    LaunchedEffect(state) {
        state.map(revision)
            .distinctUntilChanged()
            .drop(1)
            .collect { currentOnChanged() }
    }
}

private fun NavGraphBuilder.categoryRulesDestination(
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
