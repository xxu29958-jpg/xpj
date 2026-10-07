package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import com.ticketbox.data.remote.dto.ReferenceCreatedDto
import com.ticketbox.data.repository.LogicalSessionBinding

/** The raw name, original command key and complete identity survive navigation/process restoration. */
@JsonClass(generateAdapter = true)
data class ReferenceCreationDraft(
    val binding: LogicalSessionBinding,
    val key: String,
    val name: String = "",
    val phase: String = "editing",
    val receipt: ReferenceCreatedDto? = null,
    val error: String? = null,
)

internal fun LogicalSessionBinding.sameReferenceOwner(other: LogicalSessionBinding): Boolean =
    serverUrl == other.serverUrl && ledgerId == other.ledgerId && ownerKey == other.ownerKey

internal class ReferenceCreationDraftStore(private val state: SavedStateHandle) {
    private val adapter = Moshi.Builder().build().adapter<List<ReferenceCreationDraft>>(
        Types.newParameterizedType(List::class.java, ReferenceCreationDraft::class.java))
    private val drafts: List<ReferenceCreationDraft>
        get() = state.get<String>(KEY)?.let(adapter::fromJson).orEmpty()

    fun read(binding: LogicalSessionBinding): ReferenceCreationDraft? =
        drafts.lastOrNull { it.binding.sameReferenceOwner(binding) }

    fun write(draft: ReferenceCreationDraft) {
        state[KEY] = adapter.toJson(drafts.filterNot { it.key == draft.key } + draft)
    }

    fun remove(key: String) { state[KEY] = adapter.toJson(drafts.filterNot { it.key == key }) }

    private companion object { const val KEY = "reference.creation.drafts" }
}
