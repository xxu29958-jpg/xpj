package com.ticketbox.viewmodel

import com.ticketbox.domain.model.Expense
import java.time.ZoneId
import kotlinx.coroutines.flow.update

/** A review changes only unsubmitted input. It cannot rebase an existing Outbox command. */
internal data class FactCorrectionReview(
    val original: Expense,
    val current: Expense,
    val itemsChoiceRequired: Boolean,
    val splitsChoiceRequired: Boolean,
    val ready: Boolean,
)

internal fun ExpenseFactViewModel.correctionReview(): FactCorrectionReview? {
    if (correctionContextError() == null) return null
    val state = _uiState.value
    val original = correctionBaseline ?: return null
    val current = state.expense ?: return null
    val form = state.correction
    return FactCorrectionReview(original, current,
        form.itemDraftsInitialized && correctionOriginalItems?.items != state.currentCorrectionItems?.items,
        form.splitDraftsInitialized && correctionOriginalSplits?.splits != state.currentCorrectionSplits?.splits,
        state.canStartCorrection && !factInputOperationBusy() &&
            (!form.itemDraftsInitialized || state.currentCorrectionItems != null) &&
            (!form.splitDraftsInitialized || state.currentCorrectionSplits != null))
}

fun ExpenseFactViewModel.reviewCorrectionDraft(keepItems: Boolean? = null, keepSplits: Boolean? = null) {
    val review = correctionReview() ?: return
    if (!review.ready || review.itemsChoiceRequired && keepItems == null || review.splitsChoiceRequired && keepSplits == null) return
    val state = _uiState.value
    val binding = state.correctionAccess?.binding ?: return
    val form = reviewedCorrectionScalars(review.original, review.current, state.correction)
    val next = reviewedCorrectionCollections(form, state, keepItems, keepSplits)
    correctionSplitMemberGeneration++
    correctionBaseline = review.current
    correctionBinding = binding
    correctionOriginalItems = state.currentCorrectionItems
    correctionOriginalSplits = state.currentCorrectionSplits
    _uiState.update { it.copy(correction = next.copy(submitError = null, conflictMessage = null,
        itemsEditorOpen = false, splitEditorOpen = false, splitMembersLoading = false)) }
    keepCorrectionInput(review = true)
}

internal fun reviewedCorrectionScalars(old: Expense, current: Expense, form: CorrectionFormState): CorrectionFormState {
    val zone = ZoneId.of(form.expenseTimeZoneId ?: "UTC")
    val before = initialCorrectionFormState(old, zone)
    val now = initialCorrectionFormState(current, zone)
    val keepMoney = form.currencyTouched || form.amountText != before.amountText
    val timeChanged = com.ticketbox.ui.screens.expense.readExpenseTimeForm(form.timeFormJson)?.changed == true ||
        form.expenseTimeText != before.expenseTimeText
    return form.copy(
        merchant = adoptUntouched(form.merchant, before.merchant, now.merchant),
        category = adoptUntouched(form.category, before.category, now.category),
        tags = adoptUntouched(form.tags, before.tags, now.tags),
        note = adoptUntouched(form.note, before.note, now.note),
        valueScore = adoptUntouched(form.valueScore, before.valueScore, now.valueScore),
        regretScore = adoptUntouched(form.regretScore, before.regretScore, now.regretScore),
        amountText = if (keepMoney) form.amountText else now.amountText,
        currency = if (keepMoney) form.currency else now.currency,
        currencyTouched = keepMoney && (form.currencyTouched || form.currency != now.currency),
        unsupportedCurrencyCode = if (keepMoney) form.unsupportedCurrencyCode else now.unsupportedCurrencyCode,
        foreignCurrency = if (keepMoney) form.foreignCurrency else now.foreignCurrency,
        expenseTimeText = if (timeChanged) form.expenseTimeText else now.expenseTimeText,
        timeFormJson = form.timeFormJson.takeIf { timeChanged },
    )
}

private fun <T> adoptUntouched(input: T, before: T, current: T): T = if (input == before) current else input

private fun reviewedCorrectionCollections(form: CorrectionFormState, state: ExpenseFactUiState,
    keepItems: Boolean?, keepSplits: Boolean?): CorrectionFormState {
    val expense = requireNotNull(state.expense)
    val currentItems = state.currentCorrectionItems?.items.orEmpty().associateBy { it.publicId }
    val currentSplits = state.currentCorrectionSplits?.splits.orEmpty().associateBy { it.memberId }
    val retainedItems = form.itemDrafts.map { draft ->
        val current = currentItems[draft.sourcePublicId]
        if (current == null) draft else draft.copy(quantityText = current.quantityText,
            unitPriceCents = current.unitPriceCents, category = current.category, rawText = current.rawText,
            confidence = current.confidence, baselineAmountCents = current.amountCents)
    }
    // Receiver attribution and disabled historical members are not editable replacement fields.
    val retainedSplits = form.splitDrafts.map { draft ->
        val current = currentSplits[draft.memberId]
        if (current == null) draft else draft.copy(note = current.note, baselineAmountCents = current.amountCents,
            displayName = current.accountName, disabled = current.isDisabledMember,
            included = draft.included || current.isDisabledMember,
            amountText = if (current.isDisabledMember) com.ticketbox.ui.components.formatMinorAmountInput(
                kotlin.math.abs(current.amountCents), expense.editDisplayParseCurrency()) else draft.amountText)
    } + currentSplits.values.filter { it.isDisabledMember && form.splitDrafts.none { draft -> draft.memberId == it.memberId } }
        .map { EditableSplit(it.memberId, it.accountName, true,
            com.ticketbox.ui.components.formatMinorAmountInput(kotlin.math.abs(it.amountCents), expense.editDisplayParseCurrency()),
            disabled = true, note = it.note, baselineAmountCents = it.amountCents) }
    return form.copy(itemDrafts = if (keepItems == false) emptyList() else retainedItems,
        itemsTouched = keepItems != false && form.itemsTouched,
        itemDraftsInitialized = keepItems != false && form.itemDraftsInitialized,
        splitDrafts = if (keepSplits == false) emptyList() else retainedSplits,
        splitsTouched = keepSplits != false && form.splitsTouched,
        splitDraftsInitialized = keepSplits != false && form.splitDraftsInitialized)
}
