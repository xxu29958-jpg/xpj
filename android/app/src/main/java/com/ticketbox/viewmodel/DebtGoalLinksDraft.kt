package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.PendingGoalEdit
import com.ticketbox.domain.model.Goal

/** User input is retained independently from refreshed facts and admitted Room commands. */
internal data class DebtGoalLinksDraft(
    val binding: LogicalSessionBinding,
    val original: Goal,
    val selectedLabels: Map<String, String>,
) {
    val changed: Boolean get() = selectedLabels.keys != original.debtRepayment?.linkedDebts?.map { it.debtPublicId }?.toSet()
    fun matches(pending: PendingGoalEdit): Boolean = pending.row.targetId == "goal:${original.publicId}" &&
        pending.row.expectedRowVersion == original.rowVersion &&
        pending.debtLinks?.request?.debtPublicIds == selectedLabels.keys.toList()
}

internal class DebtGoalLinksDraftStore(private val state: SavedStateHandle) {
    private val adapter = Moshi.Builder().add(KotlinJsonAdapterFactory()).build().adapter<List<DebtGoalLinksDraft>>(
        Types.newParameterizedType(List::class.java, DebtGoalLinksDraft::class.java))
    private val drafts: List<DebtGoalLinksDraft> get() = state.get<String>("debt.goal.links.drafts")?.let(adapter::fromJson).orEmpty()
    fun read(binding: LogicalSessionBinding, id: String): DebtGoalLinksDraft? = drafts.lastOrNull {
        it.binding == binding && it.original.publicId == id
    }
    fun write(draft: DebtGoalLinksDraft) {
        state["debt.goal.links.drafts"] = adapter.toJson(drafts.filterNot {
            it.binding == draft.binding && it.original.publicId == draft.original.publicId
        } + draft)
    }
    fun remove(draft: DebtGoalLinksDraft) {
        state["debt.goal.links.drafts"] = adapter.toJson(drafts.filterNot { it == draft })
    }
}
