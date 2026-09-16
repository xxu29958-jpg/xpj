package com.ticketbox.ui.navigation

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
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
import androidx.compose.ui.platform.testTag
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
import com.ticketbox.data.repository.ManualExpenseCreateAdmission
import com.ticketbox.data.repository.RecurringPaymentOrigin
import com.ticketbox.data.repository.RecurringPaymentOriginLookup
import com.ticketbox.data.repository.admittedClientRef
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.DEFAULT_EXPENSE_CATEGORIES
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.ui.components.AppBusyGuardedSheet
import com.ticketbox.ui.components.formatMinorAmountInput
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.ManualExpenseSheet
import com.ticketbox.ui.screens.ManualExpenseSheetActions
import com.ticketbox.ui.screens.ManualExpenseSheetDraft
import com.ticketbox.ui.screens.ManualExpenseSheetInitials
import com.ticketbox.ui.screens.ManualExpenseSheetState
import kotlinx.coroutines.CoroutineScope
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
            admitted = { clientRef ->
                ManualExpenseSubmissionRoute(
                    clientRef,
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
    admitted: @Composable (String) -> Unit,
) {
    var accessResolved by remember { mutableStateOf(false) }
    val access by remember(factory.repository) {
        factory.repository.observeLedgerAccess().onEach { accessResolved = true }
    }.collectAsStateWithLifecycle(initialValue = null)
    var admittedResolved by remember(task.clientRef, task.binding) { mutableStateOf(false) }
    val admittedRow by remember(task.clientRef, task.binding) {
        factory.repository.manualCreation.observe(task.binding, task.clientRef).onEach { admittedResolved = true }
    }.collectAsStateWithLifecycle(initialValue = null)
    var originResolved by remember(task.binding, task.seriesPublicId, task.period, task.occurrenceRowVersion) { mutableStateOf(false) }
    val originLookup by remember(factory.repository, task.binding, task.seriesPublicId, task.period, task.occurrenceRowVersion) {
        factory.repository.manualCreation
            .observeOrigin(
                task.binding,
                RecurringPaymentOrigin(task.seriesPublicId, task.period, task.occurrenceRowVersion),
            )
            .onEach { originResolved = true }
    }.collectAsStateWithLifecycle(initialValue = RecurringPaymentOriginLookup.Absent)
    if (!recurringPaymentObservationsReady(accessResolved, admittedResolved && originResolved)) {
        Text(stringResource(R.string.recurring_payment_loading))
        return
    }
    val admittedClientRef = when (val found = originLookup) {
        is RecurringPaymentOriginLookup.Found -> found.projection.admittedClientRef()
        RecurringPaymentOriginLookup.Conflict -> null
        RecurringPaymentOriginLookup.Absent -> admittedRow?.admittedClientRef()
    }
    if (admittedClientRef != null && access?.binding == task.binding) {
        admitted(admittedClientRef)
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
                    val previous = ctx.drafts.read(task.clientRef)
                    ctx.drafts.write(
                        RecurringPaymentDraft(
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
                        ),
                    )
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
    var pendingDraft by remember { mutableStateOf<ExpenseDraft?>(null) }
    var reviewCandidates by remember { mutableStateOf<List<String>>(emptyList()) }
    val scope = rememberCoroutineScope()
    val admit: (ExpenseDraft, String, Collection<String>) -> Unit = { draft, clientRef, acknowledged ->
        if (ctx.access.context?.canModify == true && !saving) {
            saving = true
            error = null
            scope.startPeriodPaymentAdmit(ctx, draft, clientRef, acknowledged) { admission, message ->
                error = message
                if (admission is ManualExpenseCreateAdmission.Accepted) {
                    reviewCandidates = emptyList()
                    pendingDraft = null
                    ctx.drafts.remember(task.copy(clientRef = admission.clientRef))
                    ctx.drafts.removeDraft(task.clientRef)
                    draftState.removeState(task.clientRef)
                }
                if (admission is ManualExpenseCreateAdmission.ReviewRequired) {
                    pendingDraft = draft
                    reviewCandidates = admission.candidateClientRefs
                }
                saving = false
            }
        }
    }
    RecurringPaymentSheet(
        ctx.knownCurrencyBody(
            stored,
            ManualExpenseSheetState(
                categories = emptyList(),
                saving = saving,
                initialCurrency = paymentCurrency,
                ledgerHomeCurrency = home,
                errorMessage = error,
                editable = ctx.access.context?.canModify == true,
            ),
        ) { admit(it, task.clientRef, emptyList()) },
        draftState,
        task.clientRef,
        onDraftChange = { form ->
            ctx.drafts.write(RecurringPaymentDraft(task.clientRef, form.amountText, form.currency.storageKey, form.merchant, form.category, form.note, form.expenseTime))
        },
    )
    RecurringPaymentReviewHost(ctx, reviewCandidates, pendingDraft, admit) { if (!saving) reviewCandidates = emptyList() }
}

@Composable
private fun RecurringPaymentReviewHost(
    ctx: RecurringPaymentEntryContext,
    candidates: List<String>,
    pendingDraft: ExpenseDraft?,
    admit: (ExpenseDraft, String, Collection<String>) -> Unit,
    onDismiss: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    RecurringPaymentReviewDialog(
        candidates = candidates,
        onAdopt = { candidate ->
            pendingDraft?.let { draft ->
                scope.launch {
                    ctx.factory.repository.manualCreation.adoptOrigin(
                        ctx.task.binding,
                        candidate,
                        ctx.task.seriesPublicId,
                        ctx.task.period,
                        ctx.task.occurrenceRowVersion,
                    )
                    admit(draft, candidate, emptyList())
                }
            }
        },
        onConfirmUnrelated = { pendingDraft?.let { admit(it, ctx.task.clientRef, candidates) } },
        onDismiss = onDismiss,
    )
}

private fun RecurringPaymentEntryContext.knownCurrencyBody(
    stored: RecurringPaymentDraft?,
    state: ManualExpenseSheetState,
    onCreate: (ExpenseDraft) -> Unit,
) = RecurringPaymentSheetBody(
    state = state,
    actions = ManualExpenseSheetActions(onCreate, { if (!state.saving) exit.onBack() }),
    initials = ManualExpenseSheetInitials(
        merchant = stored?.merchant ?: task.merchant,
        category = stored?.category?.takeIf { it.isNotBlank() } ?: DEFAULT_EXPENSE_CATEGORIES.first(),
        note = stored?.note.orEmpty(),
        amountMinor = if (task.recordedCurrencyCode == null) null else task.suggestedAmountMinor,
        amountText = stored?.amountText,
        expenseTime = stored?.expenseTime?.takeIf { it.isNotBlank() },
    ),
)

private fun CoroutineScope.startPeriodPaymentAdmit(
    ctx: RecurringPaymentEntryContext,
    draft: ExpenseDraft,
    clientRef: String,
    acknowledged: Collection<String>,
    onDone: (ManualExpenseCreateAdmission?, String?) -> Unit,
) {
    launch {
        ctx.factory.repository.manualCreation.create(
            draft,
            ctx.task.binding,
            clientRef,
            RecurringPaymentOrigin(ctx.task.seriesPublicId, ctx.task.period, ctx.task.occurrenceRowVersion),
            acknowledged,
        ).fold({ onDone(it, null) }, { onDone(null, it.message) })
    }
}

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
private fun RecurringPaymentReviewDialog(
    candidates: List<String>,
    onAdopt: (String) -> Unit,
    onConfirmUnrelated: () -> Unit,
    onDismiss: () -> Unit,
) {
    if (candidates.isEmpty()) return
    AlertDialog(
        onDismissRequest = onDismiss,
        title = {
            Text(
                stringResource(R.string.recurring_payment_review_required),
                modifier = Modifier.testTag("recurring-payment-review"),
            )
        },
        text = {
            Column {
                candidates.forEach { candidate ->
                    TextButton(
                        onClick = { onAdopt(candidate) },
                        modifier = Modifier.testTag("recurring-payment-review-adopt"),
                    ) {
                        Text(stringResource(R.string.recurring_payment_review_adopt))
                    }
                }
            }
        },
        confirmButton = {
            TextButton(
                onClick = onConfirmUnrelated,
                modifier = Modifier.testTag("recurring-payment-review-not-this-period"),
            ) {
                Text(stringResource(R.string.recurring_payment_review_not_this_period))
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text(stringResource(R.string.common_cancel)) }
        },
    )
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
