package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import com.ticketbox.R
import com.ticketbox.data.repository.DebtCreationReceipt
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.UiText
import java.util.UUID

@JsonClass(generateAdapter = true)
internal data class DebtCreationDraft(
    val binding: LogicalSessionBinding,
    val creationKey: String = UUID.randomUUID().toString(),
    val input: DebtDraftUi = DebtDraftUi(),
    val currencyCaptured: Boolean = false,
    val publicationAttempted: Boolean = false,
) {
    val hasInput: Boolean get() = input.userTouched || input.counterpartyLabel.isNotEmpty() ||
        input.amountYuanInput.isNotEmpty() || input.note.isNotEmpty() || publicationAttempted

    fun captureContext(currency: CurrencyCode?, calendarRevision: Long?): DebtCreationDraft {
        if (publicationAttempted) return this
        val amount = if (currencyCaptured && hasInput) input else currency?.let(input::rebindHomeCurrency) ?: input
        return copy(input = amount.copy(calendarRevision = amount.calendarRevision ?: calendarRevision),
            currencyCaptured = currencyCaptured || currency != null)
    }

    fun afterPublication(result: Result<DebtCreationReceipt>): DebtCreationDraft {
        val receipt = result.getOrNull()
        if (receipt?.binding == binding && receipt.intentId > 0) {
            return DebtCreationDraft(binding, input = DebtDraftUi(homeCurrency = input.homeCurrency), currencyCaptured = true)
        }
        val error = result.exceptionOrNull()
        val rejected = (error as? RepositoryException)?.errorCode in setOf("permission_denied", "debt_create_local_input_invalid")
        return copy(publicationAttempted = publicationAttempted || !rejected,
            input = input.copy(validationError = error?.toUiText(R.string.debt_create_failed)
                ?: UiText.res(R.string.debt_create_failed)))
    }
}

/** Raw editor state per full binding; the existing Room original-creation transaction owns admission. */
internal class DebtCreationDraftStore(private val state: SavedStateHandle) {
    private val adapter = Moshi.Builder().build().adapter<List<DebtCreationDraft>>(
        Types.newParameterizedType(List::class.java, DebtCreationDraft::class.java),
    )
    private val drafts: List<DebtCreationDraft>
        get() = state.get<String>("debt.principal.creation.drafts")?.let { adapter.fromJson(it) }.orEmpty()

    fun read(binding: LogicalSessionBinding): DebtCreationDraft =
        drafts.lastOrNull { it.binding == binding } ?: DebtCreationDraft(binding).also(::write)

    fun write(draft: DebtCreationDraft) {
        state["debt.principal.creation.drafts"] = adapter.toJson(drafts.filterNot { it.binding == draft.binding } + draft)
    }

    fun settle(original: DebtCreationDraft, change: (DebtCreationDraft) -> DebtCreationDraft): DebtCreationDraft? {
        val current = drafts.lastOrNull { it.binding == original.binding && it.creationKey == original.creationKey } ?: return null
        return change(current).also(::write)
    }

    fun remove(original: DebtCreationDraft) {
        state["debt.principal.creation.drafts"] = adapter.toJson(drafts.filterNot {
            it.binding == original.binding && it.creationKey == original.creationKey
        })
    }
}
