package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import com.ticketbox.R
import com.ticketbox.data.repository.DebtCreationReceipt
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.LocalRepositoryFailure
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.data.repository.logNetworkWarning
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.UiText
import java.util.UUID
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

@JsonClass(generateAdapter = true)
internal data class DebtCreationDraft(
    val binding: LogicalSessionBinding,
    val creationKey: String = UUID.randomUUID().toString(),
    val input: DebtDraftUi = DebtDraftUi(),
    val currencyCaptured: Boolean = false,
    val publicationAttempted: Boolean = false,
    val billCaptureKey: String? = null,
    val frozenBillSource: com.ticketbox.data.remote.dto.DebtBillSourceReferenceDto? = null,
) {
    val hasInput: Boolean get() = input.userTouched || input.counterpartyLabel.isNotEmpty() ||
        input.amountYuanInput.isNotEmpty() || input.note.isNotEmpty() || publicationAttempted || billCaptureKey != null

    fun captureBill(): DebtCreationDraft = if (billCaptureKey != null) this else copy(billCaptureKey = UUID.randomUUID().toString())

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
    private val billDraftWrites = Mutex()
    private val originalAdapter = Moshi.Builder().build().adapter(DebtCreationDraft::class.java)
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

    fun encode(draft: DebtCreationDraft): String = originalAdapter.toJson(draft)

    /** Re-read inside the write lock: slow Room writes cannot publish an older editor snapshot last. */
    suspend fun persistBillDraft(sources: com.ticketbox.data.repository.DebtBillActions?, original: DebtCreationDraft): Result<Unit> = try {
        billDraftWrites.withLock {
            val latest = drafts.lastOrNull { it.binding == original.binding && it.creationKey == original.creationKey }
            latest?.billCaptureKey?.let { sources?.saveDraft(it, encode(latest)) }
        }
        Result.success(Unit)
    } catch (cancelled: kotlinx.coroutines.CancellationException) {
        throw cancelled
    } catch (error: Exception) {
        logNetworkWarning("operation=Debt bill original draft persistence", error)
        Result.failure(RepositoryException("Original input persistence unverified",
            localFailure = LocalRepositoryFailure.FactInputNotSaved, cause = error))
    }

    fun restore(raw: String, binding: LogicalSessionBinding): DebtCreationDraft =
        requireNotNull(originalAdapter.fromJson(raw)).let {
            require(it.binding.ownerKey == binding.ownerKey && it.binding.ledgerId == binding.ledgerId &&
                it.binding.serverUrl == binding.serverUrl)
            it.copy(binding = binding).also(::write)
        }

    fun resume(input: com.ticketbox.data.repository.DebtBillInput, current: DebtCreationDraft?): DebtCreationDraft {
        if (current?.hasInput == true && current.creationKey != input.payload.creationKey) {
            throw RepositoryException("请先保存或放弃当前原稿，再继续另一张账单。")
        }
        return restore(input.original.draftJson, input.binding)
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
