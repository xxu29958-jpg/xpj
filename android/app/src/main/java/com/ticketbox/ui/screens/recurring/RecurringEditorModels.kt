package com.ticketbox.ui.screens.recurring

import com.ticketbox.data.repository.RecurringItemDraft
import com.ticketbox.data.repository.RecurringItemPatch
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.ui.components.parseAmountCents
import com.ticketbox.viewmodel.RecurringManualSaveFeedback
import com.ticketbox.viewmodel.RecurringManualSaveSettlement

internal data class RecurringFormInput(
    val merchant: String,
    val amountText: String,
    val dateTouched: Boolean,
    val dateIso: String?,
)

internal enum class RecurringEditField {
    Merchant,
    Amount,
    Date,
}

internal data class RecurringOverlapComparison(
    val field: RecurringEditField,
    val value: RecurringOverlapValue,
)

internal data class RecurringOverlapDraft(
    val merchant: String,
    val amountCents: Long?,
    val amountText: String,
    val nextExpectedDate: String?,
)

internal sealed interface RecurringOverlapValue {
    data class Text(val current: String, val draft: String) : RecurringOverlapValue
    data class Amount(val currentCents: Long, val draftCents: Long) : RecurringOverlapValue
    data class RawAmount(val currentCents: Long, val draftText: String) : RecurringOverlapValue
    data class Date(val currentIso: String?, val draftIso: String?) : RecurringOverlapValue
}

/** Values already available after owner refresh; no conflict payload or second fact owner is invented. */
internal fun recurringOverlapComparisons(
    freshOwner: RecurringItem,
    overlappingFields: Set<RecurringEditField>,
    draft: RecurringOverlapDraft,
): List<RecurringOverlapComparison> = RecurringEditField.entries
    .filter(overlappingFields::contains)
    .map { field ->
        RecurringOverlapComparison(
            field = field,
            value = when (field) {
                RecurringEditField.Merchant -> RecurringOverlapValue.Text(
                    current = freshOwner.merchant,
                    draft = draft.merchant,
                )
                RecurringEditField.Amount -> draft.amountCents?.let { draftCents ->
                    RecurringOverlapValue.Amount(
                        currentCents = freshOwner.baselineAmountCents,
                        draftCents = draftCents,
                    )
                } ?: RecurringOverlapValue.RawAmount(
                    currentCents = freshOwner.baselineAmountCents,
                    draftText = draft.amountText,
                )
                RecurringEditField.Date -> RecurringOverlapValue.Date(
                    currentIso = freshOwner.nextExpectedDate,
                    draftIso = draft.nextExpectedDate,
                )
            },
        )
    }

/**
 * Safe OCC rebase for an already-open editor. User-changed fields keep the
 * draft; untouched fields adopt the fresh owner. A field is only overlapping
 * when both sides changed it to different values.
 */
internal data class RecurringEditorRebase(
    val baseline: RecurringItem,
    val merchant: String,
    val baselineAmountCents: Long,
    val nextExpectedDate: String?,
    val dateTouched: Boolean,
    val overlappingFields: Set<RecurringEditField>,
)

internal data class RecurringEditorRebaseDraft(
    val merchant: String,
    val baselineAmountCents: Long,
    val nextExpectedDate: String?,
    val previousOverlappingFields: Set<RecurringEditField> = emptySet(),
)

internal fun rebaseRecurringEditorDraft(
    previousBaseline: RecurringItem,
    freshOwner: RecurringItem,
    draft: RecurringEditorRebaseDraft,
): RecurringEditorRebase {
    val merchant = draft.merchant
    val baselineAmountCents = draft.baselineAmountCents
    val nextExpectedDate = draft.nextExpectedDate
    val merchantTouched = merchant.trim() != previousBaseline.merchant
    val amountTouched = baselineAmountCents != previousBaseline.baselineAmountCents
    val dateTouched = nextExpectedDate != previousBaseline.nextExpectedDate
    val rebasedMerchant = if (merchantTouched) merchant else freshOwner.merchant
    val rebasedAmount = if (amountTouched) baselineAmountCents else freshOwner.baselineAmountCents
    val rebasedDate = if (dateTouched) nextExpectedDate else freshOwner.nextExpectedDate
    return RecurringEditorRebase(
        baseline = freshOwner,
        merchant = rebasedMerchant,
        baselineAmountCents = rebasedAmount,
        nextExpectedDate = rebasedDate,
        dateTouched = rebasedDate != freshOwner.nextExpectedDate,
        overlappingFields = buildSet {
            addAll(draft.previousOverlappingFields.filter { field ->
                when (field) {
                    RecurringEditField.Merchant -> rebasedMerchant.trim() != freshOwner.merchant
                    RecurringEditField.Amount -> rebasedAmount != freshOwner.baselineAmountCents
                    RecurringEditField.Date -> rebasedDate != freshOwner.nextExpectedDate
                }
            })
            addOverlappingMerchant(previousBaseline, freshOwner, merchant, merchantTouched)
            addOverlappingAmount(previousBaseline, freshOwner, baselineAmountCents, amountTouched)
            addOverlappingDate(previousBaseline, freshOwner, nextExpectedDate, dateTouched)
        },
    )
}

private fun MutableSet<RecurringEditField>.addOverlappingMerchant(
    previous: RecurringItem,
    fresh: RecurringItem,
    merchant: String,
    touched: Boolean,
) {
    if (touched && fresh.merchant != previous.merchant && merchant.trim() != fresh.merchant) {
        add(RecurringEditField.Merchant)
    }
}

private fun MutableSet<RecurringEditField>.addOverlappingAmount(
    previous: RecurringItem,
    fresh: RecurringItem,
    amount: Long,
    touched: Boolean,
) {
    if (touched && fresh.baselineAmountCents != previous.baselineAmountCents &&
        amount != fresh.baselineAmountCents
    ) {
        add(RecurringEditField.Amount)
    }
}

private fun MutableSet<RecurringEditField>.addOverlappingDate(
    previous: RecurringItem,
    fresh: RecurringItem,
    date: String?,
    touched: Boolean,
) {
    if (touched && fresh.nextExpectedDate != previous.nextExpectedDate && date != fresh.nextExpectedDate) {
        add(RecurringEditField.Date)
    }
}

internal enum class RecurringFormInvalid {
    Merchant,
    Amount,
}

/** 表单提交的解析结果：要么给出要调用的写路径，要么本地拦截（校验失败 / 无改动）。 */
internal sealed interface RecurringFormSubmit {
    data class Create(val draft: RecurringItemDraft) : RecurringFormSubmit
    data class Edit(val item: RecurringItem, val patch: RecurringItemPatch) : RecurringFormSubmit
    data object DismissUnchanged : RecurringFormSubmit
    data class Invalid(val reason: RecurringFormInvalid) : RecurringFormSubmit
}

internal fun resolveRecurringFormSubmit(
    editing: RecurringItem?,
    input: RecurringFormInput,
    currency: CurrencyCode,
): RecurringFormSubmit {
    val cents = parseAmountCents(input.amountText, currency)
    return when {
        input.merchant.isBlank() -> RecurringFormSubmit.Invalid(RecurringFormInvalid.Merchant)
        cents == null || cents <= 0L -> RecurringFormSubmit.Invalid(RecurringFormInvalid.Amount)
        editing == null -> RecurringFormSubmit.Create(
            RecurringItemDraft(
                merchant = input.merchant.trim(),
                baselineAmountCents = cents,
                nextExpectedDate = input.dateIso,
            ),
        )
        else -> buildRecurringItemPatch(
            baseline = editing,
            merchant = input.merchant,
            baselineAmountCents = cents,
            dateTouched = input.dateTouched,
            nextExpectedDate = input.dateIso,
        )?.let { RecurringFormSubmit.Edit(editing, it) }
            ?: RecurringFormSubmit.DismissUnchanged
    }
}

internal enum class RecurringSubmitSettle {
    /** ViewModel 以 Danger 落定：保留表单，亮错误。 */
    Failure,
    /** 写路径已受理（Synced / Queued 待同步）：关表单，反馈交给页面横幅。 */
    Accepted,
}

/** Only the editor's exact attempt may settle it; page refresh never owns this reducer. */
internal fun recurringSubmitStep(
    awaitingAttemptId: Long?,
    feedback: RecurringManualSaveFeedback?,
): RecurringSubmitSettle? = when {
    awaitingAttemptId == null || feedback?.attemptId != awaitingAttemptId -> null
    feedback.settlement == RecurringManualSaveSettlement.InFlight -> null
    feedback.settlement == RecurringManualSaveSettlement.Accepted -> RecurringSubmitSettle.Accepted
    else -> RecurringSubmitSettle.Failure
}
