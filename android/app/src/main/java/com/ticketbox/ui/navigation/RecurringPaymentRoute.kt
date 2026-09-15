package com.ticketbox.ui.navigation

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.SaveableStateHolder
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.saveable.rememberSaveableStateHolder
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavGraphBuilder
import androidx.navigation.NavType
import androidx.navigation.compose.composable
import androidx.navigation.navArgument
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.DEFAULT_EXPENSE_CATEGORIES
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.ManualExpenseSheet
import com.ticketbox.ui.screens.ManualExpenseSheetActions
import com.ticketbox.ui.screens.ManualExpenseSheetInitials
import com.ticketbox.ui.screens.ManualExpenseSheetState
import kotlinx.coroutines.launch

internal fun NavGraphBuilder.addRecurringPaymentRoute(runtime: MainNavigationRuntime) {
    composable(RECURRING_PAYMENT_ROUTE, arguments = listOf(navArgument("task") { type = NavType.StringType })) { entry ->
        val task = readRecurringPaymentTask(entry.arguments?.getString("task")) ?: return@composable
        val back = { runtime.navController.popBackStack(); Unit }
        RecurringPaymentRoute(
            task = task,
            factory = runtime.screenFactory,
            exit = ExpenseEditExitActions(
                onBack = back,
                onCompleted = { changed ->
                    runtime.shellState.markExpenseEditCompleted()
                    if (changed) runtime.screenFactory.budgetRepository.invalidateBudgetAdvice()
                    back()
                },
            ),
            financialDataRevision = runtime.shellState.financialDataRevision,
            related = ExpenseFactNavigation(
                onOpenRepaymentDrafts = {
                    runtime.shellState.openRepaymentDrafts(it)
                    back()
                },
                onRepairRate = { binding, gap ->
                    runtime.navController.navigate(correctionRateRoute(binding, gap))
                },
            ),
        )
    }
}

@Composable
internal fun RecurringPaymentRoute(
    task: RecurringPaymentTask,
    factory: MainScreenFactory,
    exit: ExpenseEditExitActions,
    financialDataRevision: Int,
    related: ExpenseFactNavigation,
) {
    val access by remember(factory.repository) { factory.repository.observeLedgerAccess() }
        .collectAsStateWithLifecycle(initialValue = null)
    val admitted by remember(task.clientRef, task.binding) {
        factory.repository.manualCreation.observe(task.binding, task.clientRef)
    }.collectAsStateWithLifecycle(initialValue = null)
    val draftState = rememberSaveableStateHolder()
    var chosenCurrency by rememberSaveable(task.clientRef) { mutableStateOf(task.recordedCurrencyCode) }
    var saving by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    val home = CurrencyCode.fromStorageKeyOrNull(task.ledgerHomeCurrencyCode)
    val paymentCurrency = CurrencyCode.fromStorageKeyOrNull(chosenCurrency)
    val sameBinding = access?.binding == task.binding
    if (admitted != null && sameBinding) {
        ManualExpenseSubmissionRoute(task.clientRef, factory, exit, related, financialDataRevision)
        return
    }
    Column(Modifier.fillMaxSize().padding(AppSpacing.cardPadding)) {
        Text(stringResource(R.string.recurring_payment_return, task.period))
        if (!sameBinding) {
            Text(stringResource(R.string.recurring_payment_binding_changed))
            TextButton(onClick = exit.onBack) { Text(stringResource(R.string.common_cancel)) }
            return
        }
        if (home == null) {
            Text(stringResource(R.string.recurring_payment_binding_changed))
            return
        }
        if (paymentCurrency == null) {
            PeriodPaymentCurrencyChoice(
                onChoose = { chosenCurrency = it },
                onDismiss = exit.onBack,
            )
            return
        }
        RecurringPaymentSheet(
            state = ManualExpenseSheetState(
                categories = emptyList(),
                saving = saving || access?.canModify != true,
                initialCurrency = paymentCurrency,
                ledgerHomeCurrency = home,
                errorMessage = error,
            ),
            actions = ManualExpenseSheetActions(
                onCreate = { draft ->
                    if (access?.canModify == true && !saving) {
                        saving = true
                        error = null
                        scope.launch {
                            factory.repository.manualCreation.create(draft, task.binding, task.clientRef).fold(
                                onSuccess = { draftState.removeState(task.clientRef) },
                                onFailure = { error = it.message },
                            )
                            saving = false
                        }
                    }
                },
                onDismiss = { if (!saving) exit.onBack() },
            ),
            initials = ManualExpenseSheetInitials(
                merchant = task.merchant,
                category = DEFAULT_EXPENSE_CATEGORIES.first(),
                amountMinor = if (task.recordedCurrencyCode == null) null else task.suggestedAmountMinor,
            ),
            draftState = draftState,
            clientRef = task.clientRef,
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun RecurringPaymentSheet(
    state: ManualExpenseSheetState,
    actions: ManualExpenseSheetActions,
    initials: ManualExpenseSheetInitials,
    draftState: SaveableStateHolder,
    clientRef: String,
) {
    ModalBottomSheet(
        onDismissRequest = actions.onDismiss,
        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
    ) {
        draftState.SaveableStateProvider(clientRef) {
            ManualExpenseSheet(state, actions, initials)
        }
    }
}

@Composable
private fun PeriodPaymentCurrencyChoice(onChoose: (String) -> Unit, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.occurrence_payment_currency)) },
        text = {
            Column {
                Text(stringResource(R.string.occurrence_choose_payment_currency))
                CurrencyCode.entries.forEach { code ->
                    TextButton(onClick = { onChoose(code.storageKey) }) {
                        Text(code.storageKey + " · " + code.displayName)
                    }
                }
            }
        },
        confirmButton = {},
        dismissButton = {
            TextButton(onClick = onDismiss) { Text(stringResource(R.string.common_cancel)) }
        },
    )
}
