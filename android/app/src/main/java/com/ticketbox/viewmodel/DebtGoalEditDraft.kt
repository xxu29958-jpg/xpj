package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.PendingGoalEdit
import com.ticketbox.domain.model.Goal
import com.ticketbox.data.local.PendingMutationType

enum class DebtGoalEditKind(val mutationType: PendingMutationType, val savedPrefix: String) {
    Links(PendingMutationType.ReplaceGoalDebtLinks, "debt.goal.links"),
    TargetDate(PendingMutationType.SetGoalTargetDate, "debt.goal.date"),
}

/** User input is retained independently from refreshed facts and admitted Room commands. */
internal data class DebtGoalEditDraft(
    val binding: LogicalSessionBinding,
    val original: Goal,
    val selectedLabels: Map<String, String>,
    val kind: DebtGoalEditKind = DebtGoalEditKind.Links,
    val targetDate: String? = null,
) {
    val changed: Boolean get() = when (kind) {
        DebtGoalEditKind.Links -> selectedLabels.keys != original.debtRepayment?.linkedDebts?.map { it.debtPublicId }?.toSet()
        DebtGoalEditKind.TargetDate -> targetDate != original.debtRepayment?.targetDate
    }
    fun matches(pending: PendingGoalEdit): Boolean = pending.row.targetId == "goal:${original.publicId}" &&
        pending.row.expectedRowVersion == original.rowVersion && pending.row.type == kind.mutationType && when (kind) {
            DebtGoalEditKind.Links -> pending.debtEdit?.request?.debtPublicIds == selectedLabels.keys.toList()
            DebtGoalEditKind.TargetDate -> pending.debtEdit?.dateRequest?.targetDate == targetDate
        }

    fun input(): com.ticketbox.domain.model.GoalEditInput = when (kind) {
        DebtGoalEditKind.Links -> com.ticketbox.domain.model.DebtGoalLinksUpdate(original.rowVersion, selectedLabels)
        DebtGoalEditKind.TargetDate -> com.ticketbox.domain.model.DebtGoalTargetDateUpdate(original.rowVersion, targetDate)
    }
}

internal class DebtGoalEditDraftStore(private val state: SavedStateHandle, kind: DebtGoalEditKind) {
    private val key = "${kind.savedPrefix}.drafts"
    private val adapter = Moshi.Builder().add(KotlinJsonAdapterFactory()).build().adapter<List<DebtGoalEditDraft>>(
        Types.newParameterizedType(List::class.java, DebtGoalEditDraft::class.java))
    private val drafts: List<DebtGoalEditDraft> get() = state.get<String>(key)?.let(adapter::fromJson).orEmpty()
    fun read(binding: LogicalSessionBinding, id: String): DebtGoalEditDraft? = drafts.lastOrNull {
        it.binding == binding && it.original.publicId == id
    }
    fun write(draft: DebtGoalEditDraft) {
        state[key] = adapter.toJson(drafts.filterNot {
            it.binding == draft.binding && it.original.publicId == draft.original.publicId
        } + draft)
    }
    fun remove(draft: DebtGoalEditDraft) {
        state[key] = adapter.toJson(drafts.filterNot { it == draft })
    }
}
