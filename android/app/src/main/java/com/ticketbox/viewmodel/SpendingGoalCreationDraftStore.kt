package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import com.ticketbox.R
import com.ticketbox.data.repository.LocalRepositoryFailure
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.UiText
import java.time.YearMonth
import java.util.UUID

internal enum class SpendingGoalFailureKind { Create, Currency, Lookup, Validation, Amount, Recovery, MissingOriginal }

@JsonClass(generateAdapter = true)
internal data class SpendingGoalCreationFailure(
    val kind: SpendingGoalFailureKind,
    val message: String? = null,
    val code: String? = null,
    val localFailure: LocalRepositoryFailure? = null,
) {
    fun text(): UiText = when (kind) {
        SpendingGoalFailureKind.Validation -> UiText.res(R.string.spending_goal_create_validation)
        SpendingGoalFailureKind.Amount -> UiText.res(R.string.expense_edit_amount_invalid)
        SpendingGoalFailureKind.MissingOriginal -> UiText.res(R.string.goal_creation_missing)
        else -> RepositoryException(message.orEmpty(), code, localFailure = localFailure).toUiText(
            if (kind == SpendingGoalFailureKind.Currency) R.string.currency_unconfirmed_write_blocked
            else R.string.spending_goal_create_failed)
    }
}

internal fun Throwable.goalCreationFailure(kind: SpendingGoalFailureKind) = SpendingGoalCreationFailure(
    kind, message, (this as? RepositoryException)?.errorCode, (this as? RepositoryException)?.localFailure,
)

@JsonClass(generateAdapter = true)
internal data class SpendingGoalCreationDraft(
    val binding: LogicalSessionBinding,
    val creationKey: String = UUID.randomUUID().toString(),
    val name: String = "",
    val amount: String = "",
    val month: String = YearMonth.now().toString(),
    val category: String = "",
    val currencyCode: String? = null,
    val monthReady: Boolean = false,
    val monthSelected: Boolean = false,
    val userSelectedMonth: Boolean = false,
    val opened: Boolean = false,
    val publicationAttempted: Boolean = false,
    val acceptedId: Long? = null,
    val viewingOriginalId: Long? = null,
    val failure: SpendingGoalCreationFailure? = null,
    val viewFailure: SpendingGoalCreationFailure? = null,
) {
    val hasDraft: Boolean get() = opened || name.isNotEmpty() || amount.isNotEmpty() || category.isNotEmpty() ||
        userSelectedMonth || publicationAttempted

    fun presentation(canModify: Boolean) = CreateSpendingGoalUiState(canModify = canModify,
        name = name, month = month, monthReady = monthReady, targetAmountInput = amount, category = category,
        ledgerCurrency = CurrencyCode.fromStorageKeyOrNull(currencyCode),
        formError = (if (viewingOriginalId == null) failure else viewFailure)?.text(),
        creationKey = creationKey, hasDraft = hasDraft, isViewingOriginal = viewingOriginalId != null,
        originalSubmissionId = viewingOriginalId ?: acceptedId)
}

/** Each complete logical binding retains its raw task; accepted commands remain owned by Room. */
internal class SpendingGoalCreationDraftStore(private val state: SavedStateHandle) {
    private val adapter = Moshi.Builder().build().adapter<List<SpendingGoalCreationDraft>>(
        Types.newParameterizedType(List::class.java, SpendingGoalCreationDraft::class.java),
    )
    private val drafts: List<SpendingGoalCreationDraft>
        get() = state.get<String>("spending.goal.creation.drafts")?.let { adapter.fromJson(it) }.orEmpty()

    fun read(binding: LogicalSessionBinding): SpendingGoalCreationDraft? = drafts.lastOrNull { it.binding == binding }

    fun write(draft: SpendingGoalCreationDraft) {
        state["spending.goal.creation.drafts"] = adapter.toJson(drafts.filterNot { it.binding == draft.binding } + draft)
    }

    fun settle(original: SpendingGoalCreationDraft, change: (SpendingGoalCreationDraft) -> SpendingGoalCreationDraft): SpendingGoalCreationDraft? {
        val current = read(original.binding)?.takeIf { it.creationKey == original.creationKey } ?: return null
        return change(current).also(::write)
    }

    fun remove(original: SpendingGoalCreationDraft) {
        state["spending.goal.creation.drafts"] = adapter.toJson(drafts.filterNot {
            it.binding == original.binding && it.creationKey == original.creationKey
        })
    }
}
