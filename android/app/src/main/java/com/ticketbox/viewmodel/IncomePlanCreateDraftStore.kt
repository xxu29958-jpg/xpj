package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import com.squareup.moshi.FromJson
import com.squareup.moshi.ToJson
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import com.ticketbox.data.repository.LogicalSessionBinding

internal class IncomePlanCreateDraftStore(private val state: SavedStateHandle) {
    private val adapter = Moshi.Builder().add(IncomePlanCreationPhaseAdapter()).build().adapter<List<IncomePlanCreateSession>>(
        Types.newParameterizedType(List::class.java, IncomePlanCreateSession::class.java),
    )
    private val drafts: List<IncomePlanCreateSession>
        get() = state.get<String>("income.create.drafts")?.let { adapter.fromJson(it) }.orEmpty()

    fun read(binding: LogicalSessionBinding): IncomePlanCreateSession? =
        drafts.lastOrNull { it.binding == binding }?.let { it.copy(draft = it.draft.withAmountValidation()) }

    fun write(session: IncomePlanCreateSession) {
        state["income.create.drafts"] = adapter.toJson(drafts.filterNot { it.binding == session.binding } + session)
    }

    /** A late result may settle only its original command, never a newer draft under the same owner. */
    fun replaceOriginal(session: IncomePlanCreateSession) {
        if (read(session.binding)?.creationKey == session.creationKey) write(session)
    }

    fun remove(session: IncomePlanCreateSession) {
        state["income.create.drafts"] = adapter.toJson(drafts.filterNot {
            it.binding == session.binding && it.creationKey == session.creationKey
        })
    }
}

/** Unknown persisted publication phases retain the raw draft and require original-key reconciliation. */
private class IncomePlanCreationPhaseAdapter {
    @FromJson
    fun fromJson(value: String): IncomePlanCreationPhase =
        IncomePlanCreationPhase.entries.firstOrNull { it.name == value } ?: IncomePlanCreationPhase.NeedsRecovery

    @ToJson
    fun toJson(value: IncomePlanCreationPhase): String = value.name
}
