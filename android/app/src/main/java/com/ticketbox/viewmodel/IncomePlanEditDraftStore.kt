package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.PendingIncomePlanSubmission

/** Raw edits belong to their complete original identity; accepted writes belong to Room. */
internal class IncomePlanEditDraftStore(private val state: SavedStateHandle) {
    private val adapter = Moshi.Builder().build().adapter<List<IncomePlanEditSession>>(
        Types.newParameterizedType(List::class.java, IncomePlanEditSession::class.java),
    )
    private val drafts: List<IncomePlanEditSession>
        get() = state.get<String>("income.edit.drafts")?.let { adapter.fromJson(it) }.orEmpty()

    fun read(binding: LogicalSessionBinding, publicId: String? = null): IncomePlanEditSession? =
        drafts.lastOrNull { it.binding == binding && (publicId == null || it.publicId == publicId) }

    fun write(session: IncomePlanEditSession) {
        state["income.edit.drafts"] = adapter.toJson(drafts.filterNot {
            it.binding == session.binding && it.publicId == session.publicId
        } + session)
    }

    fun remove(session: IncomePlanEditSession) {
        state["income.edit.drafts"] = adapter.toJson(drafts.filterNot {
            it == session.copy(draft = session.draft.copy(validationError = null))
        })
    }

    fun removePublished(binding: LogicalSessionBinding, submissions: List<PendingIncomePlanSubmission>) {
        state["income.edit.drafts"] = adapter.toJson(drafts.filterNot { session ->
            session.binding == binding && submissions.any(session::matchesSubmission)
        })
    }
}
