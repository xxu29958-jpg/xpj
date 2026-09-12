package com.ticketbox.ui.navigation

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
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
import com.ticketbox.ui.components.AppBackButton
import com.ticketbox.ui.components.formatAmountInput
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.ManualExpensePrefill
import com.ticketbox.ui.screens.ManualExpenseSheet
import com.ticketbox.ui.screens.ManualExpenseSheetActions
import com.ticketbox.ui.screens.ManualExpenseSheetState
import kotlinx.coroutines.launch

internal fun NavGraphBuilder.addRecurringPaymentRoute(runtime: MainNavigationRuntime) {
    composable(RECURRING_PAYMENT_ROUTE, arguments = listOf(navArgument("origin") { type = NavType.StringType })) { entry ->
        val origin = readRecurringPaymentOrigin(entry.arguments?.getString("origin")) ?: return@composable
        val back = { runtime.navController.popBackStack(); Unit }
        RecurringPaymentRoute(origin, runtime.screenFactory, ExpenseEditExitActions(onBack = back, onCompleted = { changed ->
                runtime.shellState.markExpenseEditCompleted()
                if (changed) runtime.screenFactory.budgetRepository.invalidateBudgetAdvice()
                back()
            }), runtime.shellState.financialDataRevision, related = ExpenseFactNavigation(onOpenRepaymentDrafts = {
                runtime.shellState.openRepaymentDrafts(it)
                back()
            }, onRepairRate = { binding, gap ->
                runtime.navController.navigate(correctionRateRoute(binding, gap))
            }))
    }
}

@Composable
private fun RecurringPaymentRoute(
    origin: RecurringPaymentOrigin,
    factory: MainScreenFactory,
    exit: ExpenseEditExitActions,
    financialDataRevision: Int,
    related: ExpenseFactNavigation,
) {
    val clientRef = origin.clientRef ?: return
    val repository = factory.repository
    val access by remember(repository) { repository.observeLedgerAccess() }.collectAsStateWithLifecycle(initialValue = null)
    val scope = rememberCoroutineScope()
    var prepared by remember { mutableStateOf<ManualExpenseSheetState?>(null) }
    var saved by rememberSaveable { mutableStateOf(false) }
    var saving by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var attempt by remember { mutableStateOf(0) }
    val bindingChangedMessage = stringResource(R.string.recurring_payment_binding_changed)
    LaunchedEffect(origin, attempt) {
        error = null
        if (saved) return@LaunchedEffect
        repository.hasManualExpense(origin.binding, clientRef).fold(onSuccess = { exists ->
            saved = exists
            if (!exists) prepareRecurringPayment(factory, origin, bindingChangedMessage).fold(
                onSuccess = { prepared = it }, onFailure = { error = it.message })
        }, onFailure = { error = it.message })
    }
    if (saved && access?.binding == origin.binding) {
        ManualExpenseSubmissionRoute(clientRef, factory, exit, related, financialDataRevision)
        return
    }
    val sheet = prepared
    Column(Modifier.fillMaxSize().padding(AppSpacing.cardPadding)) {
        AppBackButton(text = stringResource(R.string.expense_edit_loading_back_button), onClick = exit.onBack)
        Text(stringResource(R.string.recurring_payment_return, origin.period))
        Text(error ?: stringResource(R.string.ledger_manual_currency_loading))
        TextButton(onClick = { attempt++ }, enabled = !saving) { Text(stringResource(R.string.common_retry)) }
    }
    if (sheet != null) {
        val canWrite = access?.binding == origin.binding && access?.canModify == true
        RecurringPaymentSheet(sheet.copy(saving = saving || !canWrite,
                errorMessage = if (canWrite) error else stringResource(R.string.recurring_payment_binding_changed)),
                ManualExpenseSheetActions(onCreate = { draft ->
                    if (canWrite && !saving) {
                        saving = true
                        scope.launch {
                            repository.createManualExpense(draft, origin.binding, clientRef).fold(
                                onSuccess = { saved = true }, onFailure = { error = it.message })
                            saving = false
                        }
                    }
                }, onDismiss = { if (!saving) exit.onBack() }))
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun RecurringPaymentSheet(state: ManualExpenseSheetState, actions: ManualExpenseSheetActions) {
    ModalBottomSheet(onDismissRequest = actions.onDismiss,
        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        ManualExpenseSheet(state, actions)
    }
}

private suspend fun prepareRecurringPayment(
    factory: MainScreenFactory,
    origin: RecurringPaymentOrigin,
    bindingChangedMessage: String,
): Result<ManualExpenseSheetState> =
    runCatching {
        val item = factory.recurringRepository.items(origin.binding).getOrThrow().single { it.publicId == origin.seriesPublicId }
        val currency = CurrencyCode.fromStorageKeyOrNull(item.homeCurrencyCode)
        val home = requireNotNull(CurrencyCode.fromStorageKeyOrNull(factory.debtRepository.listDebts().getOrThrow().ledgerHomeCurrencyCode))
        check(factory.repository.captureDeferredLedgerBinding() == origin.binding) { bindingChangedMessage }
        ManualExpenseSheetState(DEFAULT_EXPENSE_CATEGORIES, saving = false, initialCurrency = home,
            prefill = ManualExpensePrefill(item.merchant, currency, currency?.let { formatAmountInput(item.baselineAmountCents, it) }.orEmpty()))
    }
