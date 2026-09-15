package com.ticketbox.ui.navigation

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.SaveableStateHolder
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.saveable.rememberSaveableStateHolder
import androidx.compose.runtime.setValue
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.navigation.NavBackStackEntry
import androidx.navigation.NavGraphBuilder
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.composable
import androidx.navigation.navArgument
import com.ticketbox.R
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.RecurringPaymentOrigin
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.DEFAULT_EXPENSE_CATEGORIES
import com.ticketbox.ui.components.AppBusyGuardedSheet
import com.ticketbox.ui.components.formatMinorAmountInput
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.ManualExpenseSheet
import com.ticketbox.ui.screens.ManualExpenseSheetActions
import com.ticketbox.ui.screens.ManualExpenseSheetDraft
import com.ticketbox.ui.screens.ManualExpenseSheetInitials
import com.ticketbox.ui.screens.ManualExpenseSheetState
import kotlinx.coroutines.flow.onEach
import kotlinx.coroutines.launch

internal fun NavGraphBuilder.addRecurringPaymentRoute(runtime: MainNavigationRuntime) {
    composable(RECURRING_PAYMENT_ROUTE, arguments = listOf(navArgument("task") { type = NavType.StringType })) { entry ->
        val task = readRecurringPaymentTask(entry.arguments?.getString("task")) ?: return@composable
        val back = { runtime.navController.popBackStack(); Unit }
        val drafts = rememberRecurringPaymentDraftStore(runtime.navController, entry)
        val factory = runtime.screenFactory
        val exit = ExpenseEditExitActions(
            onBack = back,
            onCompleted = { changed ->
                runtime.shellState.markExpenseEditCompleted()
                if (changed) factory.budgetRepository.invalidateBudgetAdvice()
                back()
            },
        )
        RecurringPaymentRoute(
            task = task,
            factory = factory,
            exit = exit,
            drafts = drafts,
            admitted = {
                ManualExpenseSubmissionRoute(
                    task.clientRef,
                    factory,
                    exit,
                    related = ExpenseFactNavigation(
                        onOpenRepaymentDrafts = {
                            runtime.shellState.openRepaymentDrafts(it)
                            back()
                        },
                        onRepairRate = { binding, gap ->
                            runtime.navController.navigate(correctionRateRoute(binding, gap))
                        },
                    ),
                    financialDataRevision = runtime.shellState.financialDataRevision,
                )
            },
        )
    }
}

internal val LocalRecurringPaymentDraftHandle = staticCompositionLocalOf<SavedStateHandle?> { null }

@Composable
internal fun rememberRecurringPaymentDraftStore(
    nav: NavHostController? = null,
    paymentEntry: NavBackStackEntry? = null,
): RecurringPaymentDraftStore {
    val provided = LocalRecurringPaymentDraftHandle.current
    val ownerEntry = LocalViewModelStoreOwner.current as? NavBackStackEntry
    val mainEntry = remember(nav, paymentEntry) {
        nav?.let { runCatching { it.getBackStackEntry(MAIN_ROUTE) }.getOrNull() }
    }
    val fallback = remember { SavedStateHandle() }
    val handle = provided
        ?: mainEntry?.savedStateHandle
        ?: ownerEntry?.savedStateHandle
        ?: paymentEntry?.savedStateHandle
        ?: fallback
    val store = remember(handle) { RecurringPaymentDraftStore(handle) }
    val leftover = ownerEntry?.savedStateHandle
    LaunchedEffect(store, leftover) {
        leftover?.let(store::adoptLegacyPeriodPaymentSessions)
    }
    return store
}

private data class RecurringPaymentAccess(
    val resolved: Boolean,
    val context: LedgerAccessContext?,
)

private data class RecurringPaymentEntryContext(
    val task: RecurringPaymentTask,
    val factory: MainScreenFactory,
    val exit: ExpenseEditExitActions,
    val drafts: RecurringPaymentDraftStore,
    val access: RecurringPaymentAccess,
)

internal data class RecurringPaymentSheetBody(
    val state: ManualExpenseSheetState,
    val actions: ManualExpenseSheetActions,
    val initials: ManualExpenseSheetInitials,
)

@Composable
internal fun RecurringPaymentRoute(
    task: RecurringPaymentTask,
    factory: MainScreenFactory,
    exit: ExpenseEditExitActions,
    drafts: RecurringPaymentDraftStore,
    admitted: @Composable () -> Unit,
) {
    var accessResolved by remember { mutableStateOf(false) }
    val access by remember(factory.repository) {
        factory.repository.observeLedgerAccess().onEach { accessResolved = true }
    }.collectAsStateWithLifecycle(initialValue = null)
    var admittedResolved by remember(task.clientRef, task.binding) { mutableStateOf(false) }
    val admittedRow by remember(task.clientRef, task.binding) {
        factory.repository.manualCreation.observe(task.binding, task.clientRef).onEach { admittedResolved = true }
    }.collectAsStateWithLifecycle(initialValue = null)
    if (!recurringPaymentObservationsReady(accessResolved, admittedResolved)) {
        Text(stringResource(R.string.recurring_payment_loading))
        return
    }
    if (admittedRow != null && access?.binding == task.binding) {
        admitted()
        return
    }
    RecurringPaymentEntry(
        RecurringPaymentEntryContext(
            task, factory, exit, drafts, RecurringPaymentAccess(accessResolved, access),
        ),
    )
}

@Composable
private fun RecurringPaymentEntry(ctx: RecurringPaymentEntryContext) {
    val task = ctx.task
    val stored = ctx.drafts.read(task.clientRef)
    var chosenCurrency by rememberSaveable(task.clientRef) {
        mutableStateOf(stored?.currencyCode ?: task.recordedCurrencyCode)
    }
    val home = CurrencyCode.fromStorageKeyOrNull(task.ledgerHomeCurrencyCode)
    val paymentCurrency = CurrencyCode.fromStorageKeyOrNull(chosenCurrency)
    val sameBinding = ctx.access.context?.binding == task.binding
    Column(Modifier.fillMaxSize().padding(AppSpacing.cardPadding)) {
        Text(stringResource(R.string.recurring_payment_return, task.period))
        if (recurringPaymentShowsBindingChanged(ctx.access.resolved, sameBinding)) {
            Text(stringResource(R.string.recurring_payment_binding_changed))
            TextButton(onClick = ctx.exit.onBack) { Text(stringResource(R.string.common_cancel)) }
            return
        }
        if (home == null) {
            Text(stringResource(R.string.recurring_payment_binding_changed))
            return
        }
        if (paymentCurrency == null) {
            PeriodPaymentCurrencyChoice(
                onChoose = { code ->
                    chosenCurrency = code
                    ctx.drafts.write(currencyChoiceDraft(task, ctx.drafts.read(task.clientRef), code))
                },
                onDismiss = ctx.exit.onBack,
            )
            return
        }
        RecurringPaymentKnownCurrencySheet(ctx, home, paymentCurrency)
    }
}

@Composable
private fun RecurringPaymentKnownCurrencySheet(
    ctx: RecurringPaymentEntryContext,
    home: CurrencyCode,
    paymentCurrency: CurrencyCode,
) {
    val task = ctx.task
    val stored = ctx.drafts.read(task.clientRef)
    val draftState = rememberSaveableStateHolder()
    var saving by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    RecurringPaymentSheet(
        RecurringPaymentSheetBody(
            state = ManualExpenseSheetState(
                categories = emptyList(),
                saving = saving || ctx.access.context?.canModify != true,
                initialCurrency = paymentCurrency,
                ledgerHomeCurrency = home,
                errorMessage = error,
            ),
            actions = ManualExpenseSheetActions(
                onCreate = { draft ->
                    if (ctx.access.context?.canModify == true && !saving) {
                        saving = true
                        error = null
                        scope.launch {
                            ctx.factory.repository.manualCreation.create(
                                draft,
                                task.binding,
                                task.clientRef,
                                RecurringPaymentOrigin(task.seriesPublicId, task.period),
                            ).fold(
                                onSuccess = {
                                    ctx.drafts.removeDraft(task.clientRef)
                                    draftState.removeState(task.clientRef)
                                },
                                onFailure = { error = it.message },
                            )
                            saving = false
                        }
                    }
                },
                onDismiss = { if (!saving) ctx.exit.onBack() },
            ),
            initials = ManualExpenseSheetInitials(
                merchant = stored?.merchant ?: task.merchant,
                category = stored?.category ?: DEFAULT_EXPENSE_CATEGORIES.first(),
                note = stored?.note.orEmpty(),
                amountMinor = if (task.recordedCurrencyCode == null) null else task.suggestedAmountMinor,
                amountText = stored?.amountText,
                expenseTime = stored?.expenseTime?.takeIf { it.isNotBlank() },
            ),
        ),
        draftState,
        task.clientRef,
        onDraftChange = { form -> ctx.drafts.write(formDraft(task.clientRef, form)) },
    )
}

private fun currencyChoiceDraft(
    task: RecurringPaymentTask,
    previous: RecurringPaymentDraft?,
    code: String,
) = RecurringPaymentDraft(
    clientRef = task.clientRef,
    amountText = previous?.amountText ?: formatMinorAmountInput(
        task.suggestedAmountMinor,
        CurrencyCode.fromStorageKeyOrNull(code) ?: CurrencyCode.CNY,
    ),
    currencyCode = code,
    merchant = previous?.merchant ?: task.merchant,
    category = previous?.category ?: DEFAULT_EXPENSE_CATEGORIES.first(),
    note = previous?.note.orEmpty(),
    expenseTime = previous?.expenseTime.orEmpty(),
)

private fun formDraft(clientRef: String, form: ManualExpenseSheetDraft) = RecurringPaymentDraft(
    clientRef = clientRef,
    amountText = form.amountText,
    currencyCode = form.currency.storageKey,
    merchant = form.merchant,
    category = form.category,
    note = form.note,
    expenseTime = form.expenseTime,
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun RecurringPaymentSheet(
    body: RecurringPaymentSheetBody,
    draftState: SaveableStateHolder,
    clientRef: String,
    onDraftChange: (ManualExpenseSheetDraft) -> Unit,
) {
    AppBusyGuardedSheet(
        isSubmitting = body.state.saving,
        onDismiss = body.actions.onDismiss,
        skipPartiallyExpanded = true,
    ) {
        draftState.SaveableStateProvider(clientRef) {
            ManualExpenseSheet(body.state, body.actions, body.initials, onDraftChange = onDraftChange)
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
