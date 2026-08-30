package com.ticketbox.ui.screens.recurring

import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
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

/** 编辑器打开目标：新建，或编辑某条已发布项（active/paused 才会进来，archived 不给编辑）。 */
internal sealed interface RecurringEditorTarget {
    data object Create : RecurringEditorTarget
    data class Edit(val item: RecurringItem) : RecurringEditorTarget
}

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
    target: RecurringEditorTarget?,
    uiState: RecurringUiState,
    environment: RecurringEditorEnvironment,
    actions: RecurringItemActions,
) {
    if (target == null) return
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    ModalBottomSheet(onDismissRequest = environment.onDismiss, sheetState = sheetState) {
        RecurringEditorSheet(
            target = target,
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
    target: RecurringEditorTarget,
    uiState: RecurringUiState,
    actions: RecurringItemActions,
    environment: RecurringEditorEnvironment,
) {
    // 与 IncomePlan 表单同一约定：display home 仅作展示兜底，写面由 VM 账本 binding 守门。
    val currency = environment.currencyDisplay.homeCurrency
    val session = rememberRecurringEditorSession(target, currency)
    val ownerState = recurringEditorOwnerState(session, uiState)
    RecurringEditorRebaseEffect(session, ownerState, uiState.itemsLoadState, currency)
    RecurringSubmitSettleEffect(
        session = session,
        feedback = ownerState.attemptFeedback,
        onAccepted = environment.onDismiss,
    )
    RecurringEditorContent(session, ownerState, actions, environment)
}

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
        if (session.rebaseUi?.attemptId == conflict.attemptId) return@LaunchedEffect
        if (ownerLoadState != RecurringListLoadState.Loaded || !ownerState.ownerIsFresh) return@LaunchedEffect
        val parsedAmount = parseAmountCents(session.amountText, currency) ?: return@LaunchedEffect
        val rebase = rebaseRecurringEditorDraft(
            previousBaseline = previousBaseline,
            freshOwner = checkNotNull(ownerState.freshOwner),
            merchant = session.merchant,
            baselineAmountCents = parsedAmount,
            nextExpectedDate = session.dateIso,
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
            primaryText = stringResource(
                recurringPrimaryActionTextRes(session.submitUi.awaiting, ownerState.stage),
            ),
            primaryEnabled = !session.submitUi.awaiting && ownerState.stage != RecurringRebaseStage.LoadingOwner,
        ),
        callbacks = recurringEditorCallbacks(session, ownerState, actions, environment),
        feedback = RecurringEditorFeedback(
            errorText = session.submitUi.error,
            conflict = environment.conflict,
            conflictStatus = recurringConflictStatus(ownerState.stage),
            onConflictAction = environment.onConflictAction,
        ),
    )
}

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
