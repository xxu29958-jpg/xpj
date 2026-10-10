package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.R
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.PendingGoalEdit
import com.ticketbox.data.repository.toRequest
import com.ticketbox.data.repository.validatedGoalUpdate
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.GoalUpdate
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.parseAmountCents

/** Original editable input is separate from current reads and admitted Room commands. */
internal data class SpendingGoalEditDraft(
    val binding: LogicalSessionBinding,
    val original: Goal,
    val name: String,
    val month: String,
    val amount: String,
    val category: String,
) {
    fun matchesSubmission(pending: PendingGoalEdit): Boolean {
        val currency = CurrencyCode.fromStorageKeyOrNull(original.homeCurrencyCode) ?: return false
        val cents = parseAmountCents(amount, currency) ?: return false
        val request = GoalUpdate(original.rowVersion, name, month, cents, category, currency.storageKey)
            .validatedGoalUpdate().getOrNull()?.toRequest() ?: return false
        return pending.row.targetId == "goal:${original.publicId}" &&
            pending.row.expectedRowVersion == original.rowVersion && pending.request == request
    }
}

class SpendingGoalEditDraftStore(private val state: SavedStateHandle) : ViewModel() {
    private val adapter = Moshi.Builder().add(KotlinJsonAdapterFactory()).build().adapter<List<SpendingGoalEditDraft>>(
        Types.newParameterizedType(List::class.java, SpendingGoalEditDraft::class.java),
    )
    private val drafts: List<SpendingGoalEditDraft>
        get() = state.get<String>("spending.goal.edit.drafts")?.let { adapter.fromJson(it) }.orEmpty()

    internal fun read(binding: LogicalSessionBinding, publicId: String): SpendingGoalEditDraft? =
        drafts.lastOrNull { it.binding == binding && it.original.publicId == publicId }

    internal fun write(draft: SpendingGoalEditDraft) {
        state["spending.goal.edit.drafts"] = adapter.toJson(drafts.filterNot {
            it.binding == draft.binding && it.original.publicId == draft.original.publicId
        } + draft)
    }

    internal fun remove(draft: SpendingGoalEditDraft) {
        state["spending.goal.edit.drafts"] = adapter.toJson(drafts.filterNot { it == draft })
    }
}

internal fun SpendingGoalDetailUiState.withEditDraft(draft: SpendingGoalEditDraft?): SpendingGoalDetailUiState =
    if (draft == null) this else copy(editOriginal = draft.original, name = draft.name, month = draft.month,
        targetAmountInput = draft.amount, category = draft.category,
        formError = spendingGoalAmountError(draft.amount, CurrencyCode.fromStorageKeyOrNull(draft.original.homeCurrencyCode)) ?: formError)

internal fun spendingGoalAmountError(value: String, currency: CurrencyCode?): UiText? =
    if (value.isNotBlank() && currency != null && parseAmountCents(value, currency) == null)
        UiText.res(R.string.expense_edit_amount_invalid) else null
