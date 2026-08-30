package com.ticketbox.ui.screens.recurring

import androidx.annotation.StringRes
import androidx.compose.runtime.Composable
import androidx.compose.runtime.MutableState
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.ui.components.formatAmountInput
import com.ticketbox.ui.screens.RecurringItemActions
import com.ticketbox.viewmodel.RecurringListLoadState
import com.ticketbox.viewmodel.RecurringManualSaveFeedback
import com.ticketbox.viewmodel.RecurringManualSaveSettlement
import com.ticketbox.viewmodel.RecurringUiState

/** 提交等待态以本轮 attempt id 落定；页面 refresh 不拥有它。 */
internal data class RecurringSubmitUi(
    val attemptId: Long? = null,
    val awaiting: Boolean = false,
    val error: String? = null,
)

internal data class RecurringRebaseUi(
    val attemptId: Long,
    val overlappingFields: Set<RecurringEditField>,
)

internal enum class RecurringRebaseStage {
    None,
    LoadingOwner,
    OwnerUnavailable,
    Ready,
    Overlapping,
}

internal class RecurringDraftStates(
    val editing: MutableState<RecurringItem?>,
    val merchant: MutableState<String>,
    val amountText: MutableState<String>,
    val dateIso: MutableState<String?>,
    val dateTouched: MutableState<Boolean>,
)

internal class RecurringInteractionStates(
    val showDatePicker: MutableState<Boolean>,
    val submitUi: MutableState<RecurringSubmitUi>,
    val rebaseUi: MutableState<RecurringRebaseUi?>,
)

/**
 * The bottom sheet's local draft and attempt state. This is presentation state:
 * published recurring facts and OCC remain owned by the repository/backend.
 */
@Stable
internal class RecurringEditorSession internal constructor(
    private val draft: RecurringDraftStates,
    private val interaction: RecurringInteractionStates,
) {
    var editing by draft.editing
    var merchant by draft.merchant
    var amountText by draft.amountText
    var dateIso by draft.dateIso
    var dateTouched by draft.dateTouched
    var showDatePicker by interaction.showDatePicker
    var submitUi by interaction.submitUi
    var rebaseUi by interaction.rebaseUi

    fun applyRebase(rebase: RecurringEditorRebase, attemptId: Long, currency: CurrencyCode) {
        merchant = rebase.merchant
        amountText = formatAmountInput(rebase.baselineAmountCents, currency)
        dateIso = rebase.nextExpectedDate
        dateTouched = rebase.dateTouched
        editing = rebase.baseline
        rebaseUi = RecurringRebaseUi(attemptId, rebase.overlappingFields)
    }

    fun submit(
        actions: RecurringItemActions,
        currency: CurrencyCode,
        merchantError: String,
        amountError: String,
        onDismiss: () -> Unit,
    ) {
        val input = RecurringFormInput(merchant, amountText, dateTouched, dateIso)
        when (val result = resolveRecurringFormSubmit(editing, input, currency)) {
            is RecurringFormSubmit.Invalid -> submitUi = RecurringSubmitUi(
                error = if (result.reason == RecurringFormInvalid.Merchant) merchantError else amountError,
            )
            RecurringFormSubmit.DismissUnchanged -> onDismiss()
            is RecurringFormSubmit.Create -> startAttempt(actions.onCreate(result.draft))
            is RecurringFormSubmit.Edit -> startAttempt(actions.onEdit(result.item, result.patch))
        }
    }

    private fun startAttempt(attemptId: Long) {
        submitUi = RecurringSubmitUi(attemptId = attemptId, awaiting = true)
    }
}

@Composable
internal fun rememberRecurringEditorSession(
    target: RecurringEditorTarget,
    currency: CurrencyCode,
): RecurringEditorSession {
    val baseline = (target as? RecurringEditorTarget.Edit)?.item
    val fieldKey = baseline?.publicId ?: "create"
    val draft = RecurringDraftStates(
        editing = remember(fieldKey) { mutableStateOf(baseline) },
        merchant = rememberSaveable(fieldKey) { mutableStateOf(baseline?.merchant.orEmpty()) },
        amountText = rememberSaveable(fieldKey) {
            mutableStateOf(baseline?.let { formatAmountInput(it.baselineAmountCents, currency) } ?: "")
        },
        dateIso = rememberSaveable(fieldKey) {
            mutableStateOf(baseline?.nextExpectedDate ?: recurringDefaultNextDate())
        },
        dateTouched = rememberSaveable(fieldKey) { mutableStateOf(false) },
    )
    val interaction = RecurringInteractionStates(
        showDatePicker = rememberSaveable(fieldKey) { mutableStateOf(false) },
        submitUi = remember(fieldKey) { mutableStateOf(RecurringSubmitUi()) },
        rebaseUi = remember(fieldKey) { mutableStateOf(null) },
    )
    return RecurringEditorSession(draft, interaction)
}

internal data class RecurringEditorOwnerState(
    val attemptFeedback: RecurringManualSaveFeedback?,
    val conflict: RecurringManualSaveFeedback?,
    val freshOwner: RecurringItem?,
    val ownerIsFresh: Boolean,
    val stage: RecurringRebaseStage,
)

internal fun recurringEditorOwnerState(
    session: RecurringEditorSession,
    uiState: RecurringUiState,
): RecurringEditorOwnerState {
    val feedback = uiState.manualSaveFeedback?.takeIf { it.attemptId == session.submitUi.attemptId }
    val conflict = feedback?.takeIf {
        it.settlement == RecurringManualSaveSettlement.Failed && it.requiresOwnerReload
    }
    val baseline = session.editing
    val freshOwner = baseline?.let { owner ->
        uiState.items.firstOrNull { it.publicId == owner.publicId }
    }
    val ownerIsFresh = baseline?.let { owner ->
        freshOwner?.rowVersion?.let { it > owner.rowVersion }
    } ?: false
    return RecurringEditorOwnerState(
        attemptFeedback = feedback,
        conflict = conflict,
        freshOwner = freshOwner,
        ownerIsFresh = ownerIsFresh,
        stage = recurringRebaseStage(conflict, session.rebaseUi, uiState.itemsLoadState, ownerIsFresh),
    )
}

private fun recurringRebaseStage(
    ownerConflict: RecurringManualSaveFeedback?,
    rebaseUi: RecurringRebaseUi?,
    ownerLoadState: RecurringListLoadState,
    ownerIsFresh: Boolean,
): RecurringRebaseStage {
    ownerConflict ?: return RecurringRebaseStage.None
    if (rebaseUi?.attemptId == ownerConflict.attemptId) {
        return if (rebaseUi.overlappingFields.isEmpty()) {
            RecurringRebaseStage.Ready
        } else {
            RecurringRebaseStage.Overlapping
        }
    }
    return when {
        ownerLoadState == RecurringListLoadState.Loading -> RecurringRebaseStage.LoadingOwner
        ownerLoadState == RecurringListLoadState.Loaded && ownerIsFresh -> RecurringRebaseStage.LoadingOwner
        else -> RecurringRebaseStage.OwnerUnavailable
    }
}

@StringRes
internal fun recurringPrimaryActionTextRes(
    awaiting: Boolean,
    stage: RecurringRebaseStage,
): Int = when {
    awaiting -> R.string.recurring_form_saving
    stage == RecurringRebaseStage.LoadingOwner -> R.string.recurring_form_loading_latest
    stage == RecurringRebaseStage.OwnerUnavailable -> R.string.recurring_form_reload_latest
    stage == RecurringRebaseStage.Overlapping -> R.string.recurring_form_save_mine
    stage == RecurringRebaseStage.Ready -> R.string.recurring_form_save_again
    else -> R.string.recurring_form_save
}

internal fun recurringEditorDraftEnabled(
    awaiting: Boolean,
    stage: RecurringRebaseStage,
): Boolean = !awaiting &&
    stage != RecurringRebaseStage.LoadingOwner &&
    stage != RecurringRebaseStage.OwnerUnavailable
