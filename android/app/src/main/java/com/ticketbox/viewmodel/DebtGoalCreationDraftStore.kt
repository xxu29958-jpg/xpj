package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import com.ticketbox.R
import com.ticketbox.data.repository.LocalRepositoryFailure
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.UiText
import java.util.UUID

@JsonClass(generateAdapter = true)
internal data class DebtGoalCreationFailure(
    val resource: Int? = null,
    val message: String? = null,
    val code: String? = null,
    val localFailure: LocalRepositoryFailure? = null,
) {
    fun text(): UiText = resource?.let { UiText.res(it) }
        ?: RepositoryException(message.orEmpty(), code, localFailure = localFailure).toUiText(R.string.debt_goal_create_failed)
}

internal fun Throwable.debtGoalCreationFailure() = DebtGoalCreationFailure(
    message = message, code = (this as? RepositoryException)?.errorCode,
    localFailure = (this as? RepositoryException)?.localFailure,
)

@JsonClass(generateAdapter = true)
internal data class DebtGoalCreationDraft(
    val binding: LogicalSessionBinding,
    val creationKey: String = UUID.randomUUID().toString(),
    val name: String = "",
    val selectedIds: List<String> = emptyList(),
    val publicationAttempted: Boolean = false,
    val acceptedId: Long? = null,
    val viewingOriginalId: Long? = null,
    val failure: DebtGoalCreationFailure? = null,
    val viewFailure: DebtGoalCreationFailure? = null,
) {
    val hasDraft: Boolean get() = name.isNotEmpty() || selectedIds.isNotEmpty() || publicationAttempted || acceptedId != null
}

/** SavedState owns raw drafts per complete binding; Room remains the command owner. */
internal class DebtGoalCreationDraftStore(private val state: SavedStateHandle) {
    private val adapter = Moshi.Builder().build().adapter<List<DebtGoalCreationDraft>>(
        Types.newParameterizedType(List::class.java, DebtGoalCreationDraft::class.java),
    )
    private val drafts: List<DebtGoalCreationDraft>
        get() = state.get<String>("debt.goal.creation.drafts")?.let { adapter.fromJson(it) }.orEmpty()

    fun read(binding: LogicalSessionBinding): DebtGoalCreationDraft? = drafts.lastOrNull { it.binding == binding }

    fun write(draft: DebtGoalCreationDraft) {
        state["debt.goal.creation.drafts"] = adapter.toJson(drafts.filterNot { it.binding == draft.binding } + draft)
    }

    fun settle(original: DebtGoalCreationDraft, change: (DebtGoalCreationDraft) -> DebtGoalCreationDraft): DebtGoalCreationDraft? {
        val current = read(original.binding)?.takeIf { it.creationKey == original.creationKey } ?: return null
        return change(current).also(::write)
    }

    fun remove(original: DebtGoalCreationDraft) {
        state["debt.goal.creation.drafts"] = adapter.toJson(drafts.filterNot {
            it.binding == original.binding && it.creationKey == original.creationKey
        })
    }
}
