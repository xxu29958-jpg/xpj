package com.ticketbox.ui.navigation

import android.net.Uri
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import androidx.navigation.NavBackStackEntry
import androidx.navigation.NavGraphBuilder
import androidx.navigation.NavType
import androidx.navigation.compose.composable
import androidx.navigation.navArgument
import com.ticketbox.data.remote.dto.SavedViewDefinitionRequestDto
import com.ticketbox.data.repository.queryDefinition
import com.ticketbox.ui.design.LocalCurrencyCode
import com.ticketbox.ui.screens.SavedQueryActions
import com.ticketbox.ui.screens.SavedQueryEditor
import com.ticketbox.ui.screens.SavedQueryEditorActions
import com.ticketbox.ui.screens.SavedQueryEditorContext
import com.ticketbox.ui.screens.SavedQueryScreen
import com.ticketbox.viewmodel.SavedQueryViewModel

internal fun savedQueryCreationRoute(query: String, category: String, month: String) =
    "${ProductSecondaryPage.SavedQueries.route}?create=yes&q=${Uri.encode(query)}&category=${Uri.encode(category)}&month=${Uri.encode(month)}"

internal fun NavGraphBuilder.savedQueryRoute(dependencies: MainProductRouteDependencies) {
    val arguments = listOf("create", "q", "category", "month").map { key -> navArgument(key) { type = NavType.StringType; defaultValue = "" } }
    composable("${ProductSecondaryPage.SavedQueries.route}?create={create}&q={q}&category={category}&month={month}", arguments) { entry ->
        SavedQueryRoute(entry, dependencies)
    }
}

@Composable
private fun SavedQueryRoute(entry: NavBackStackEntry, dependencies: MainProductRouteDependencies) {
    val screenFactory = dependencies.screenFactory
    val model: SavedQueryViewModel = viewModel(factory = viewModelFactory {
        initializer { SavedQueryViewModel(screenFactory.savedQueryRepository, screenFactory.tagRepository) }
    })
    val state by model.state.collectAsStateWithLifecycle()
    val drafts by model.drafts.state.collectAsStateWithLifecycle()
    val currency = LocalCurrencyCode.current.storageKey
    var slot by rememberSaveable { mutableStateOf<String?>(null) }
    var initialHandled by rememberSaveable { mutableStateOf(false) }
    val create = {
        val month = entry.arguments?.getString("month").orEmpty()
        slot = model.drafts.begin(SavedViewDefinitionRequestDto("", if (month.isBlank()) "current" else "fixed",
            month.ifBlank { null }, "", null, currency, entry.arguments?.getString("q").orEmpty(), entry.arguments?.getString("category").orEmpty()))
    }
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) {
        model.refresh()
    }
    LaunchedEffect(drafts.ready, drafts.canModify) {
        if (!initialHandled && drafts.ready && drafts.canModify && entry.arguments?.getString("create") == "yes") {
            create()
            initialHandled = true
        }
    }
    val draft = drafts.drafts.firstOrNull { it.slot == slot }
    LaunchedEffect(slot, drafts.drafts, drafts.ready) { if (slot != null && drafts.ready && draft == null) slot = null }
    if (draft != null) {
        SavedQueryEditor(draft, drafts, SavedQueryEditorContext(screenFactory.ledgerRepository.currentLedgerName().orEmpty(), state.tags, state.tagError),
            SavedQueryEditorActions(change = { model.drafts.change(draft.slot, it) }, submit = { model.drafts.submit(draft.slot) },
                review = { model.drafts.review(draft.slot) }, acknowledge = { model.drafts.acknowledge(draft.slot) },
                retrySave = { model.drafts.retrySave(draft.slot) }, back = { slot = null; model.refresh() }))
    } else SavedQueryScreen(state, drafts, SavedQueryActions(
        back = { if (state.selectedId == null) dependencies.onBack() else model.closeResults() },
        create = create, open = model::open, edit = { query, delete -> slot = model.drafts.begin(query.queryDefinition(), query, delete) },
        resume = { slot = it.slot }, refresh = { model.drafts.reload(); model.refresh() }, openExpense = dependencies.runtime.navController::openExpense,
        repairRate = { gap -> drafts.binding?.let { dependencies.runtime.navController.navigate(correctionRateRoute(it, gap)) } },
    ))
}
