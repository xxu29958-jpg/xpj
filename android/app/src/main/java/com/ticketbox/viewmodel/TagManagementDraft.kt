package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.domain.model.ManagedTag

enum class TagEditorAction { Rename, Merge, Delete }

@JsonClass(generateAdapter = true)
data class TagEditorDraft(
    val action: TagEditorAction,
    val source: ManagedTag,
    val requireOrphan: Boolean = false,
    val name: String = source.name,
    val target: ManagedTag? = null,
)

@JsonClass(generateAdapter = true)
internal data class TagManagementDraft(
    val binding: LogicalSessionBinding,
    val editor: TagEditorDraft?,
)

/** Raw form and its original identity/OCC; accepted tag commands remain online-only. */
internal class TagManagementDraftStore(private val state: SavedStateHandle) {
    private val adapter = Moshi.Builder().build().adapter(TagManagementDraft::class.java)

    fun read(): TagManagementDraft? = state.get<String>(KEY)?.let(adapter::fromJson)

    fun write(binding: LogicalSessionBinding, editor: TagEditorDraft?) {
        state[KEY] = adapter.toJson(TagManagementDraft(binding, editor))
    }

    private companion object { const val KEY = "tag-management.draft" }
}
