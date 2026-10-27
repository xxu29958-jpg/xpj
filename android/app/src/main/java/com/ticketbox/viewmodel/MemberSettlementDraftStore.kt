package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import com.ticketbox.data.repository.DebtTask
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.MemberSettlementCommand
import com.ticketbox.data.repository.MemberSettlementCommandJson
import com.ticketbox.viewmodel.readExpenseTimeForm
import com.ticketbox.viewmodel.toSavedJson

/** This is an original online request, not an accepted fact or an offline Outbox command. */
data class MemberSettlementAttempt(val command: MemberSettlementCommand, val key: String, val rejected: Boolean = false)

@JsonClass(generateAdapter = true)
data class MemberSettlementContext(val counterpartyLabel: String?, val viewerIsDebtor: Boolean?)

@JsonClass(generateAdapter = true)
internal data class MemberSettlementDraftSnapshot(
    val binding: LogicalSessionBinding,
    val debtPublicId: String,
    val form: ProposalForm?,
    val proposalPublicId: String?,
    val amount: String,
    val note: String,
    val currencyCode: String?,
    val expectedRowVersion: Long?,
    val proposedAmount: Long?,
    val commandKind: String?,
    val commandJson: String?,
    val commandKey: String?,
    val rejected: Boolean,
    val context: MemberSettlementContext? = null,
    val paymentTimeJson: String? = null,
)

/** SavedState belongs to the existing editing owner; server commands and receipts keep their owners. */
internal class MemberSettlementDraftStore(private val savedState: SavedStateHandle) {
    private val moshi = Moshi.Builder().build()
    private val adapter = moshi.adapter<List<MemberSettlementDraftSnapshot>>(
        Types.newParameterizedType(List::class.java, MemberSettlementDraftSnapshot::class.java),
    )
    private var snapshots: List<MemberSettlementDraftSnapshot>
        get() = savedState.get<String>("member.repayment.drafts")?.let { adapter.fromJson(it) }.orEmpty()
        set(value) { savedState["member.repayment.drafts"] = adapter.toJson(value) }

    fun read(task: DebtTask): MemberProposalUiState? {
        val value = snapshots.firstOrNull { it.binding == task.binding && it.debtPublicId == task.debtPublicId } ?: return null
        val original = value.commandKey?.let { key ->
            MemberSettlementAttempt(MemberSettlementCommandJson.read(requireNotNull(value.commandKind), requireNotNull(value.commandJson)), key, value.rejected)
        }
        return MemberProposalUiState(task = task, retainedForm = value.form, targetProposalPublicId = value.proposalPublicId,
            amountInput = value.amount, noteInput = value.note, formCurrencyCode = value.currencyCode,
            formRowVersion = value.expectedRowVersion, formProposedAmount = value.proposedAmount, originalAttempt = original,
            originalContext = value.context, paymentTime = readExpenseTimeForm(value.paymentTimeJson))
    }

    fun write(state: MemberProposalUiState) {
        val task = state.task ?: return
        if (state.retainedForm == null && state.originalAttempt == null) return
        val original = state.originalAttempt
        val commandJson = original?.command?.let { MemberSettlementCommandJson.write(it) }
        val snapshot = MemberSettlementDraftSnapshot(task.binding, task.debtPublicId, state.retainedForm, state.targetProposalPublicId,
            state.amountInput, state.noteInput, state.formCurrencyCode, state.formRowVersion, state.formProposedAmount,
            original?.command?.let { command -> MemberSettlementCommandJson.kind(command) },
            commandJson, original?.key, original?.rejected == true, state.originalContext, state.paymentTime?.toSavedJson())
        snapshots = snapshots.filterNot { it.binding == task.binding && it.debtPublicId == task.debtPublicId } + snapshot
    }

    fun remove(task: DebtTask) {
        snapshots = snapshots.filterNot { it.binding == task.binding && it.debtPublicId == task.debtPublicId }
    }
}
