package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import com.ticketbox.data.repository.DebtTask
import com.ticketbox.data.repository.LogicalSessionBinding

@JsonClass(generateAdapter = true)
internal data class SplitAgreementDraftSnapshot(
    val binding: LogicalSessionBinding,
    val debtPublicId: String,
    val currencyCode: String?,
    val share: String,
    val settlement: String,
    val reason: String,
    val settlementEdited: Boolean,
    val replacingProposalPublicId: String?,
) {
    fun restore(task: DebtTask) = SplitAgreementUiState(task = task, draftCurrencyCode = currencyCode,
        shareInput = share, settlementInput = settlement, reason = reason, settlementEdited = settlementEdited,
        replacingProposalPublicId = replacingProposalPublicId, hasDraft = true)
}

/** Saved state retains raw input only; agreement facts and command acceptance retain their existing owners. */
internal class SplitAgreementDraftStore(private val state: SavedStateHandle) {
    private val adapter = Moshi.Builder().build().adapter<List<SplitAgreementDraftSnapshot>>(
        Types.newParameterizedType(List::class.java, SplitAgreementDraftSnapshot::class.java),
    )
    private val drafts: List<SplitAgreementDraftSnapshot>
        get() = state.get<String>("split.agreement.drafts")?.let { adapter.fromJson(it) }.orEmpty()

    fun read(task: DebtTask): SplitAgreementUiState? =
        drafts.firstOrNull { it.binding == task.binding && it.debtPublicId == task.debtPublicId }?.restore(task)

    fun write(value: SplitAgreementUiState) {
        val task = value.task ?: return
        if (!value.hasDraft) return
        val snapshot = SplitAgreementDraftSnapshot(task.binding, task.debtPublicId, value.draftCurrencyCode,
            value.shareInput, value.settlementInput, value.reason, value.settlementEdited, value.replacingProposalPublicId)
        state["split.agreement.drafts"] = adapter.toJson(drafts.filterNot {
            it.binding == task.binding && it.debtPublicId == task.debtPublicId
        } + snapshot)
    }
}
