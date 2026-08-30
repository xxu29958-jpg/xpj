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

internal fun rebaseRecurringEditorDraft(
    previousBaseline: RecurringItem,
    freshOwner: RecurringItem,
    merchant: String,
    baselineAmountCents: Long,
    nextExpectedDate: String?,
): RecurringEditorRebase {
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
