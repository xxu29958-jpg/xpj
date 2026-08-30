package com.ticketbox.ui.screens.recurring

import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.SheetValue
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.parseAmountCents
import com.ticketbox.ui.screens.RecurringItemActions
import com.ticketbox.viewmodel.RecurringListLoadState
import com.ticketbox.viewmodel.RecurringManualSaveFeedback
import com.ticketbox.viewmodel.RecurringUiState

internal data class RecurringEditorEnvironment(
    val currencyDisplay: CurrencyDisplay,
    val conflict: RecurringConflictModel?,
    val onRefresh: () -> Unit,
    val onDismiss: () -> Unit,
    val onConflictAction: (RecurringConflictModel) -> Unit,
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun RecurringEditorSheetHost(
    editor: RecurringEditorState?,
    uiState: RecurringUiState,
    environment: RecurringEditorEnvironment,
    actions: RecurringItemActions,
) {
    if (editor == null) return
    // Only the VM flag needs updated-state capture; session.submitUi.awaiting is
    // snapshot-backed, so callbacks read it live at invocation time.
    val vmSaveInFlight = rememberUpdatedState(uiState.manualSaveInFlight)
    val sheetState = rememberModalBottomSheetState(
        skipPartiallyExpanded = true,
        confirmValueChange = { targetValue ->
            recurringEditorSheetAllowsTransition(
                session = editor.session,
                manualSaveInFlight = vmSaveInFlight.value,
                targetValue = targetValue,
            )
        },
    )
    val submitUi = editor.session.submitUi
    // Material3 consults confirmValueChange once, before the hide mutation wins
    // the AnchoredDraggableState drag mutex, and publishes the Hidden target only
    // after winning it. A Back/scrim hide authorized just before this attempt can
    // therefore still read Expanded/Expanded here and publish Hidden afterwards
    // without re-asking. Claim visibility once per in-flight attempt: the fresh
    // show() mutation preempts that stale pre-authorized hide (and reverses an
    // already published Hidden), so a failed settlement cannot strand the draft
    // and error behind a hidden sheet. Settlement is deliberately not an effect
    // key: awaiting=false must neither cancel an in-flight show() nor retrigger
    // it, so after a failure the user can still dismiss normally.
    LaunchedEffect(submitUi.attemptId) {
        if (recurringEditorAttemptRequiresVisibility(submitUi.attemptId, submitUi.awaiting)) {
            sheetState.show()
        }
    }
    ModalBottomSheet(
        onDismissRequest = {
            val sessionAwaiting = editor.session.submitUi.awaiting
            if (!sessionAwaiting && !vmSaveInFlight.value) environment.onDismiss()
        },
        sheetState = sheetState,
    ) {
        RecurringEditorSheet(
            session = editor.session,
            uiState = uiState,
            actions = actions,
            environment = environment,
        )
    }
}

/**
 * 添加 / 编辑固定支出共用表单。不乐观关闭：提交后等 ViewModel 落定，成功（含
 * Queued 待同步）才关；失败保留表单亮错误。撞单（recurring_item_conflict）时
 * 冲突块直接给「查看/编辑现有记录」「恢复这条记录」出口。
 */
@Composable
internal fun RecurringEditorSheet(
    session: RecurringEditorSession,
    uiState: RecurringUiState,
    actions: RecurringItemActions,
    environment: RecurringEditorEnvironment,
) {
    // 与 IncomePlan 表单同一约定：display home 仅作展示兜底，写面由 VM 账本 binding 守门。
    val currency = environment.currencyDisplay.homeCurrency
    val ownerState = recurringEditorOwnerState(session, uiState)
    RecurringEditorRebaseEffect(session, ownerState, uiState.itemsLoadState, currency)
    RecurringSubmitSettleEffect(
        session = session,
        feedback = ownerState.attemptFeedback,
        onAccepted = environment.onDismiss,
    )
    RecurringEditorContent(
        session = session,
        ownerState = ownerState,
        actions = actions,
        environment = environment,
        mutationInFlight = uiState.mutationInFlight,
    )
}

@OptIn(ExperimentalMaterial3Api::class)
internal fun recurringEditorSheetAllowsTransition(
    session: RecurringEditorSession,
    manualSaveInFlight: Boolean,
    targetValue: SheetValue,
): Boolean = targetValue != SheetValue.Hidden ||
    !(session.submitUi.awaiting || manualSaveInFlight)

/**
 * Once-per-attempt visibility ownership. While a submit attempt is in flight the
 * sheet must be (or become) visible — unconditionally of the sheet's current or
 * target value, because a hide authorized before the attempt may not have
 * published its Hidden target yet (drag-mutex timing). Once the attempt settles,
 * the same attemptId stops claiming visibility, so a post-failure dismiss stays
 * dismissed and is never force-reopened by a stale attempt.
 */
internal fun recurringEditorAttemptRequiresVisibility(
    attemptId: Long?,
    awaiting: Boolean,
): Boolean = attemptId != null && awaiting

@Composable
private fun RecurringEditorRebaseEffect(
    session: RecurringEditorSession,
    ownerState: RecurringEditorOwnerState,
    ownerLoadState: RecurringListLoadState,
    currency: CurrencyCode,
) {
    LaunchedEffect(ownerState.conflict?.attemptId, ownerLoadState, ownerState.freshOwner?.rowVersion) {
        val conflict = ownerState.conflict ?: return@LaunchedEffect
        val previousBaseline = session.editing ?: return@LaunchedEffect
        if (ownerLoadState != RecurringListLoadState.Loaded || !ownerState.ownerIsFresh) return@LaunchedEffect
        val parsedAmount = parseAmountCents(session.amountText, currency) ?: return@LaunchedEffect
        val previousOverlaps = session.rebaseUi
            ?.takeIf { it.attemptId == conflict.attemptId }
            ?.overlappingFields
            .orEmpty()
        val rebase = rebaseRecurringEditorDraft(
            previousBaseline = previousBaseline,
            freshOwner = checkNotNull(ownerState.freshOwner),
            draft = RecurringEditorRebaseDraft(
                merchant = session.merchant,
                baselineAmountCents = parsedAmount,
                nextExpectedDate = session.dateIso,
                previousOverlappingFields = previousOverlaps,
            ),
        )
        session.applyRebase(rebase, conflict.attemptId, currency)
    }
}

@Composable
private fun RecurringEditorContent(
    session: RecurringEditorSession,
    ownerState: RecurringEditorOwnerState,
    actions: RecurringItemActions,
    environment: RecurringEditorEnvironment,
    mutationInFlight: Boolean,
) {
    val currency = environment.currencyDisplay.homeCurrency
    RecurringEditorForm(
        title = stringResource(
            if (session.editing == null) R.string.recurring_form_title_create else R.string.recurring_form_title_edit,
        ),
        state = RecurringEditorFormState(
            merchant = session.merchant,
            // Candidate identity suppresses the already-claimed suggestion.
            // Cross-merchant reassignment needs a separate provenance owner;
            // this editor keeps the name visible and the other fields usable.
            merchantEditable = session.editing == null || session.editing?.source == "manual",
            amountText = session.amountText,
            currency = currency,
            dateIso = session.dateIso,
            showDatePicker = session.showDatePicker,
            awaiting = session.submitUi.awaiting,
            // generic mutation 在途时表单与提交同禁：页面一次只结算一个命令。
            draftEnabled = recurringEditorDraftEnabled(session.submitUi.awaiting, ownerState.stage) &&
                !mutationInFlight,
            primaryText = stringResource(
                recurringPrimaryActionTextRes(session.submitUi.awaiting, ownerState.stage),
            ),
            primaryEnabled = !session.submitUi.awaiting &&
                ownerState.stage != RecurringRebaseStage.LoadingOwner &&
                !mutationInFlight,
        ),
        callbacks = recurringEditorCallbacks(session, ownerState, actions, environment),
        feedback = RecurringEditorFeedback(
            errorText = session.submitUi.error,
            conflict = environment.conflict,
            conflictStatus = recurringConflictStatus(ownerState.stage),
            overlaps = session.overlapComparisons(ownerState, currency),
            onConflictAction = environment.onConflictAction,
        ),
    )
}

private fun RecurringEditorSession.overlapComparisons(
    ownerState: RecurringEditorOwnerState,
    currency: CurrencyCode,
): List<RecurringOverlapComparison> {
    if (ownerState.stage != RecurringRebaseStage.Overlapping) return emptyList()
    // 展示面优先新鲜 owner；OCC 保存基线仍是 session.editing。
    val freshOwner = recurringOverlapDisplayOwner(ownerState.freshOwner, editing) ?: return emptyList()
    val fields = rebaseUi?.overlappingFields.orEmpty()
    return recurringOverlapComparisons(
        freshOwner = freshOwner,
        overlappingFields = fields,
        draft = RecurringOverlapDraft(
            merchant = merchant,
            amountCents = parseAmountCents(amountText, currency),
            amountText = amountText,
            nextExpectedDate = dateIso,
        ),
    )
}

/** overlap「当前记录」展示面：优先新鲜 owner，fallback 会话 OCC 基线。 */
internal fun recurringOverlapDisplayOwner(
    freshOwner: RecurringItem?,
    editingBaseline: RecurringItem?,
): RecurringItem? = freshOwner ?: editingBaseline

@Composable
private fun recurringEditorCallbacks(
    session: RecurringEditorSession,
    ownerState: RecurringEditorOwnerState,
    actions: RecurringItemActions,
    environment: RecurringEditorEnvironment,
): RecurringEditorFormCallbacks {
    val merchantError = stringResource(R.string.recurring_form_error_merchant)
    val amountError = stringResource(R.string.recurring_form_error_amount)
    return RecurringEditorFormCallbacks(
        onMerchant = { session.merchant = it },
        onAmount = { session.amountText = it },
        date = RecurringDateCallbacks(
            onPick = { session.showDatePicker = true },
            onClear = { session.dateIso = null; session.dateTouched = true },
            onSelect = { selected ->
                session.dateIso = selected
                session.dateTouched = true
                session.showDatePicker = false
            },
            onDismiss = { session.showDatePicker = false },
        ),
        onSubmit = {
            if (ownerState.stage == RecurringRebaseStage.OwnerUnavailable) {
                environment.onRefresh()
            } else {
                session.submit(
                    actions = actions,
                    currency = environment.currencyDisplay.homeCurrency,
                    merchantError = merchantError,
                    amountError = amountError,
                    onDismiss = environment.onDismiss,
                )
            }
        },
        onCancel = environment.onDismiss,
    )
}

@Composable
private fun recurringConflictStatus(stage: RecurringRebaseStage): Pair<String, MessageTone>? = when (stage) {
    RecurringRebaseStage.None -> null
    RecurringRebaseStage.LoadingOwner ->
        stringResource(R.string.recurring_form_conflict_loading) to MessageTone.Info
    RecurringRebaseStage.OwnerUnavailable ->
        stringResource(R.string.recurring_form_conflict_unavailable) to MessageTone.Danger
    RecurringRebaseStage.Ready ->
        stringResource(R.string.recurring_form_conflict_rebased) to MessageTone.Info
    RecurringRebaseStage.Overlapping ->
        stringResource(R.string.recurring_form_conflict_overlapping) to MessageTone.Danger
}

@Composable
private fun RecurringSubmitSettleEffect(
    session: RecurringEditorSession,
    feedback: RecurringManualSaveFeedback?,
    onAccepted: () -> Unit,
) {
    val messageText = feedback?.message?.asString()
    LaunchedEffect(session.submitUi.attemptId, feedback) {
        if (!session.submitUi.awaiting) return@LaunchedEffect
        when (recurringSubmitStep(session.submitUi.attemptId, feedback)) {
            RecurringSubmitSettle.Failure -> session.submitUi = session.submitUi.copy(
                awaiting = false,
                error = messageText,
            )
            RecurringSubmitSettle.Accepted -> onAccepted()
            null -> Unit
        }
    }
}
