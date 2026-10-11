package com.ticketbox.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.ViewModelStoreOwner
import com.ticketbox.ui.screens.settings.ReferenceCreationEntry
import androidx.navigation.NavHostController
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.ticketbox.domain.model.CategoryReference
import com.ticketbox.domain.model.CategoryReferenceKind
import com.ticketbox.ui.screens.transactions.CategoryDirectoryScreen
import com.ticketbox.viewmodel.CategoryDirectoryViewModel
import com.ticketbox.viewmodel.categoryDirectoryViewModelFactory

@Composable
internal fun CategoryDirectoryRoute(
    navController: NavHostController,
    screenFactory: MainScreenFactory,
    onVocabularyChanged: () -> Unit,
    creationOwner: () -> ViewModelStoreOwner,
) {
    val viewModel: CategoryDirectoryViewModel = viewModel(
        key = transactionsLibraryViewModelKey(
            "category-directory",
            screenFactory.ledgerRepository.activeLedgerId(),
        ),
        factory = categoryDirectoryViewModelFactory(screenFactory.categoryPreferenceRepository),
    )
    var returningFromReference by rememberSaveable(screenFactory.ledgerRepository.activeLedgerId()) { mutableStateOf(false) }
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    DisposableEffect(lifecycle, viewModel) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME && returningFromReference) {
                returningFromReference = false
                viewModel.refresh()
            }
        }
        lifecycle.addObserver(observer)
        onDispose { lifecycle.removeObserver(observer) }
    }
    CategoryDirectoryScreen(
        viewModel = viewModel,
        onBack = navController::popBackStack,
        onCategoriesChanged = onVocabularyChanged,
        creation = { ready ->
            ReferenceCreationEntry(screenFactory.categoryPreferenceRepository.creation, creationOwner(), ready,
                onCreated = { viewModel.refresh(); onVocabularyChanged() },
                onRecycle = { returningFromReference = true; navController.navigate(TRANSACTIONS_LIBRARY_RECYCLE_BIN_ROUTE) })
        },
        onOpenReference = {
            returningFromReference = true
            navController.navigate(categoryReferenceRoute(it))
        },
    )
}

private fun categoryReferenceRoute(reference: CategoryReference): String = when (reference.kind) {
    CategoryReferenceKind.Rule -> categoryRuleEditRoute(reference.id.toLong())
    CategoryReferenceKind.Budget -> budgetRoute(reference.id)
    CategoryReferenceKind.SpendingGoal -> goalEditRoute(reference.id)
}
