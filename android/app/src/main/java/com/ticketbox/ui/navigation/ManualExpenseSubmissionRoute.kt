package com.ticketbox.ui.navigation

import android.net.Uri
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavGraphBuilder
import androidx.navigation.NavType
import androidx.navigation.compose.composable
import androidx.navigation.navArgument
import com.ticketbox.ui.screens.settings.SyncStatusNavigation
import com.ticketbox.ui.screens.settings.SyncStatusScreen
import com.ticketbox.viewmodel.OutboxRecoveryRepositories
import com.ticketbox.viewmodel.OutboxStatusViewModel
import com.ticketbox.viewmodel.outboxStatusViewModelFactory
import kotlinx.coroutines.flow.map

private const val MANUAL_CLIENT_REF_ARG = "clientRef"
internal const val MANUAL_EXPENSE_SUBMISSION_ROUTE = "manual-submission/{$MANUAL_CLIENT_REF_ARG}"

internal fun manualExpenseSubmissionRoute(clientRef: String): String = "manual-submission/${Uri.encode(clientRef)}"

internal fun NavGraphBuilder.addManualExpenseSubmissionRoute(runtime: MainNavigationRuntime) {
    composable(MANUAL_EXPENSE_SUBMISSION_ROUTE,
        arguments = listOf(navArgument(MANUAL_CLIENT_REF_ARG) { type = NavType.StringType })) { entry ->
        val ref = entry.arguments?.getString(MANUAL_CLIENT_REF_ARG) ?: return@composable
        ManualExpenseSubmissionRoute(ref, runtime.screenFactory,
            onBack = { runtime.navController.popBackStack() },
            onCompleted = { adviceInputsChanged ->
                runtime.shellState.markExpenseEditCompleted()
                if (adviceInputsChanged) runtime.screenFactory.budgetRepository.invalidateBudgetAdvice()
                runtime.navController.popBackStack()
            },
            related = ExpenseFactNavigation(onOpenRepaymentDrafts = {
                runtime.shellState.openRepaymentDrafts(it)
                runtime.navController.popBackStack()
            }, onRepairRate = { binding, gap -> runtime.navController.navigate(correctionRateRoute(binding, gap)) }))
    }
}

/** The original submission is already owned by Outbox; a local row is never a server fact URL. */
@Composable
internal fun ManualExpenseSubmissionRoute(
    clientRef: String,
    screenFactory: MainScreenFactory,
    onBack: () -> Unit,
    onCompleted: (Boolean) -> Unit,
    related: ExpenseFactNavigation,
) {
    val binding by remember(screenFactory) { screenFactory.repository.observeLedgerAccess().map { it?.binding } }
        .collectAsStateWithLifecycle(initialValue = screenFactory.repository.captureDeferredLedgerBinding())
    // The saved destination selection belongs to this original and complete binding, including after Back.
    key(clientRef, binding) {
        var openedExpense by rememberSaveable { mutableStateOf<Long?>(null) }
        val id = openedExpense
        if (id != null) {
            ExpenseEditRoute(id, screenFactory, onBack, onCompleted, related)
            return@key
        }
        val vm: OutboxStatusViewModel = viewModel(key = "manual-submission-$clientRef",
            factory = outboxStatusViewModelFactory(screenFactory.outboxRepository, screenFactory.repository,
                OutboxRecoveryRepositories(screenFactory.debtCreationRepository, screenFactory.recurringRepository.occurrences,
                    screenFactory.incomePlanRepository, screenFactory.debtAdjustmentRepository, screenFactory.goalEditRepository,
                    screenFactory.budgetRepository, screenFactory.recurringRepository, screenFactory.ruleRepository)))
        SyncStatusScreen(vm, onBack, manualClientRef = clientRef, navigation = SyncStatusNavigation(
            onOpenExpense = { if (it > 0 && binding != null &&
                binding == screenFactory.repository.captureDeferredLedgerBinding()) openedExpense = it },
            onOpenInbox = {}, onOpenBudget = {}, onOpenRecurring = {}, onOpenGoalCreation = {}, onOpenGoalEdit = {},
            onOpenRuleSubmission = {}, onOpenIncomeSubmission = {}, onOpenRateSubmission = {},
            onRepairCorrectionRate = related.onRepairRate))
    }
}
