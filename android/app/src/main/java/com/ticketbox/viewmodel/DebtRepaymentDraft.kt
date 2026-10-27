package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.PendingDebtWrite
import com.ticketbox.domain.model.Debt
import com.ticketbox.viewmodel.ExpenseTimeForm
import java.time.Clock
import java.time.LocalDate
import java.time.ZoneId

/** Unpublished input and its original read belong to the existing detail editing task. */
@JsonClass(generateAdapter = true)
internal data class DebtRepaymentDraft(
    val binding: LogicalSessionBinding,
    val target: Debt,
    val amount: String,
    val paymentTime: ExpenseTimeForm,
    val key: String,
)

internal class DebtRepaymentDraftStore(private val savedState: SavedStateHandle) {
    private val adapter = Moshi.Builder().build().adapter<List<DebtRepaymentDraft>>(
        Types.newParameterizedType(List::class.java, DebtRepaymentDraft::class.java),
    )
    private var drafts: List<DebtRepaymentDraft>
        get() = savedState.get<String>("debt.repayment.drafts")?.let { adapter.fromJson(it) }.orEmpty()
        set(value) { savedState["debt.repayment.drafts"] = adapter.toJson(value) }

    fun read(binding: LogicalSessionBinding, publicId: String): DebtRepaymentDraft? =
        drafts.firstOrNull { it.binding == binding && it.target.publicId == publicId }

    fun write(state: DebtDetailUiState) {
        if (state.activeAction != DebtAction.Repayment) return
        val binding = state.binding ?: return
        val target = state.actionTarget ?: return
        val time = state.paymentTime ?: return
        val key = state.repaymentKey ?: return
        drafts = drafts.filterNot { it.binding == binding && it.target.publicId == target.publicId } +
            DebtRepaymentDraft(binding, target, state.amountInput, time, key)
    }

    fun remove(binding: LogicalSessionBinding, publicId: String, key: String?) {
        drafts = drafts.filterNot { it.binding == binding && it.target.publicId == publicId && it.key == key }
    }

    /** A durable original Outbox row takes ownership even if the publication callback was lost. */
    fun published(binding: LogicalSessionBinding, publicId: String, rows: List<PendingDebtWrite>): String? {
        val original = read(binding, publicId) ?: return null
        if (rows.none { it.row.idempotencyKey == original.key && it.repayment != null }) return null
        remove(binding, publicId, original.key)
        return original.key
    }
}

internal fun initialDebtPaymentTime(debt: Debt?, clock: Clock): ExpenseTimeForm {
    val calendar = debt?.repaymentCalendar
    val zone = calendar?.timezoneName?.let(ZoneId::of) ?: clock.zone
    return ExpenseTimeForm.dateOnly(LocalDate.now(clock.withZone(zone)).toString(), calendar?.revision, zone.id)
}

internal fun DebtDetailUiState.withPublishedRepayment(key: String?): DebtDetailUiState {
    if (key == null) return this
    return if (activeAction == DebtAction.Repayment && repaymentKey == key) {
        copy(activeAction = null, actionTarget = null, amountInput = "", paymentTime = null,
            repaymentKey = null, hasRepaymentDraft = false, isSubmitting = false, validationError = null)
    } else copy(hasRepaymentDraft = false)
}
