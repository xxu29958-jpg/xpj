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
    val scalars: List<CorrectionScalarComparison>,
)

internal enum class CorrectionReviewField { Money, Time, Merchant, Category, Tags, Note, ValueScore, RegretScore }

internal data class CorrectionScalarComparison(
    val field: CorrectionReviewField,
    val current: String,
    val proposed: String,
    val conflict: Boolean,
)

internal data class CorrectionReviewSelection(
    val currentVersion: Long,
    val scalars: Map<CorrectionReviewField, Boolean> = emptyMap(),
    val keepItems: Boolean? = null,
    val keepSplits: Boolean? = null,
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
            (!form.splitDraftsInitialized || state.currentCorrectionSplits != null),
        correctionScalarComparisons(original, current, form))
}

internal fun ExpenseFactViewModel.reviewCorrectionDraft(selection: CorrectionReviewSelection) {
    val review = correctionReview() ?: return
    if (!review.ready || review.current.rowVersion != selection.currentVersion ||
        review.itemsChoiceRequired && selection.keepItems == null || review.splitsChoiceRequired && selection.keepSplits == null ||
        review.scalars.any { it.conflict && it.field !in selection.scalars }) return
    val state = _uiState.value
    val binding = state.correctionAccess?.binding ?: return
    val form = reviewedCorrectionScalars(review.original, review.current, state.correction, selection.scalars)
    val next = reviewedCorrectionCollections(form, state, selection.keepItems, selection.keepSplits)
    correctionSplitMemberGeneration++
    correctionBaseline = review.current
    correctionBinding = binding
    correctionOriginalItems = state.currentCorrectionItems
    correctionOriginalSplits = state.currentCorrectionSplits
    _uiState.update { it.copy(correction = next.copy(submitError = null, conflictMessage = null,
        itemsEditorOpen = false, splitEditorOpen = false, splitMembersLoading = false)) }
    keepCorrectionInput(review = true)
}

internal fun reviewedCorrectionScalars(old: Expense, current: Expense, form: CorrectionFormState,
    choices: Map<CorrectionReviewField, Boolean>): CorrectionFormState {
    val zone = ZoneId.of(form.expenseTimeZoneId ?: "UTC")
    val before = initialCorrectionFormState(old, zone)
    val now = initialCorrectionFormState(current, zone)
    val keepMoney = choices[CorrectionReviewField.Money] != false && moneyChanged(form, before)
    val timeChanged = choices[CorrectionReviewField.Time] != false && timeChanged(form, before)
    return form.copy(
        merchant = adoptUntouched(form.merchant, before.merchant, now.merchant, choices[CorrectionReviewField.Merchant]),
        category = adoptUntouched(form.category, before.category, now.category, choices[CorrectionReviewField.Category]),
        tags = adoptUntouched(form.tags, before.tags, now.tags, choices[CorrectionReviewField.Tags]),
        note = adoptUntouched(form.note, before.note, now.note, choices[CorrectionReviewField.Note]),
        valueScore = adoptUntouched(form.valueScore, before.valueScore, now.valueScore, choices[CorrectionReviewField.ValueScore]),
        regretScore = adoptUntouched(form.regretScore, before.regretScore, now.regretScore, choices[CorrectionReviewField.RegretScore]),
        amountText = if (keepMoney) form.amountText else now.amountText,
        currency = if (keepMoney) form.currency else now.currency,
        currencyTouched = keepMoney && (form.currencyTouched || form.currency != now.currency),
        unsupportedCurrencyCode = if (keepMoney) form.unsupportedCurrencyCode else now.unsupportedCurrencyCode,
        foreignCurrency = if (keepMoney) form.foreignCurrency else now.foreignCurrency,
        expenseTimeText = if (timeChanged) form.expenseTimeText else now.expenseTimeText,
        timeFormJson = form.timeFormJson.takeIf { timeChanged },
    )
}

private fun <T> adoptUntouched(input: T, before: T, current: T, keep: Boolean?): T =
    if (input == before || keep == false) current else input

private fun moneyChanged(form: CorrectionFormState, before: CorrectionFormState): Boolean =
    form.currencyTouched || form.amountText != before.amountText

private fun timeChanged(form: CorrectionFormState, before: CorrectionFormState): Boolean =
    com.ticketbox.ui.screens.expense.readExpenseTimeForm(form.timeFormJson)?.changed == true || form.expenseTimeText != before.expenseTimeText

internal fun correctionScalarComparisons(old: Expense, current: Expense, form: CorrectionFormState): List<CorrectionScalarComparison> {
    val zone = ZoneId.of(form.expenseTimeZoneId ?: "UTC")
    val before = initialCorrectionFormState(old, zone)
    val now = initialCorrectionFormState(current, zone)
    fun money(value: CorrectionFormState) = "${value.unsupportedCurrencyCode ?: value.currency.storageKey} ${value.amountText}"
    fun time(value: CorrectionFormState, expense: Expense): String {
        val captured = com.ticketbox.ui.screens.expense.readExpenseTimeForm(value.timeFormJson)
        if (captured == null && value.expenseTimeText != initialCorrectionFormState(expense, zone).expenseTimeText) return value.expenseTimeText
        val displayed = captured ?: com.ticketbox.ui.screens.expense.ExpenseTimeForm.initial(expense.expenseTime, expense.accountingTime, null, zone)
        return if (displayed.precision == "date_only") displayed.date else listOf(displayed.date, displayed.time, displayed.sourceZone)
            .filter { it.isNotBlank() }.joinToString(" · ")
    }
    val rows = mutableListOf<CorrectionScalarComparison>()
    fun add(field: CorrectionReviewField, previous: String, latest: String, input: String, changed: Boolean = input != previous) {
        if (changed) rows += CorrectionScalarComparison(field, latest, input, previous != latest && input != latest)
    }
    add(CorrectionReviewField.Money, money(before), money(now), money(form), moneyChanged(form, before))
    add(CorrectionReviewField.Time, time(before, old), time(now, current), time(form, old), timeChanged(form, before))
    add(CorrectionReviewField.Merchant, before.merchant, now.merchant, form.merchant)
    add(CorrectionReviewField.Category, before.category, now.category, form.category)
    add(CorrectionReviewField.Tags, before.tags, now.tags, form.tags)
    add(CorrectionReviewField.Note, before.note, now.note, form.note)
    add(CorrectionReviewField.ValueScore, before.valueScore?.toString().orEmpty(), now.valueScore?.toString().orEmpty(), form.valueScore?.toString().orEmpty())
    add(CorrectionReviewField.RegretScore, before.regretScore?.toString().orEmpty(), now.regretScore?.toString().orEmpty(), form.regretScore?.toString().orEmpty())
    return rows
}

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
