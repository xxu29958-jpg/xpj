package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.remote.dto.SavedViewDefinitionRequestDto
import com.ticketbox.data.remote.dto.SavedViewDto
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.data.repository.SavedQueryCommand
import com.ticketbox.data.repository.SavedQueryDraft
import com.ticketbox.data.repository.SavedQueryRepository
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import java.util.UUID

data class SavedQueryDraftState(
    val binding: LogicalSessionBinding? = null,
    val drafts: List<SavedQueryDraft> = emptyList(),
    val ready: Boolean = false,
    val canModify: Boolean = false,
    val busy: Boolean = false,
    val error: UiText? = null,
) {
    fun canEdit(draft: SavedQueryDraft) = ready && canModify && !busy && draft.binding == binding && draft.phase == "editing"
    fun canSubmit(draft: SavedQueryDraft) = ready && canModify && !busy && error == null && draft.binding == binding &&
        draft.phase in setOf("editing", "unconfirmed") && draft.definition.name.isNotBlank()
}

/** The original command survives navigation, process recreation and an unknown HTTP outcome. */
class SavedQueryDraftController(
    private val repository: SavedQueryRepository,
    private val scope: CoroutineScope,
    private val onAccepted: () -> Unit,
) {
    private val owner = repository.captureBinding()
    private var access: LedgerAccessContext? = null
    private var retained = emptyList<SavedQueryDraft>()
    private val writes = Mutex()
    private val _state = MutableStateFlow(SavedQueryDraftState())
    val state = _state.asStateFlow()

    init {
        scope.launch { repository.observeAccess().collect { access = it; publish() } }
        reload()
    }

    fun reload() {
        val binding = owner ?: return
        if (_state.value.ready || _state.value.busy) return
        _state.value = _state.value.copy(busy = true)
        scope.launch {
            repository.readDrafts(binding).onSuccess { retained = it; _state.value = _state.value.copy(ready = true, error = null) }
                .onFailure { _state.value = _state.value.copy(error = UiText.res(R.string.saved_query_input_read_failed)) }
            _state.value = _state.value.copy(busy = false)
            publish()
        }
    }

    private fun publish(draft: SavedQueryDraft? = null) {
        if (draft != null) retained = retained.filterNot { it.slot == draft.slot } + draft
        val current = access
        val sameOwner = current != null && owner?.sameReferenceOwner(current.binding) == true
        _state.value = _state.value.copy(binding = current?.binding,
            canModify = sameOwner && current?.canModify == true, drafts = if (sameOwner) retained else emptyList())
    }

    fun begin(definition: SavedViewDefinitionRequestDto, baseline: SavedViewDto? = null, delete: Boolean = false): String? {
        val current = _state.value
        if (!current.ready || !current.canModify || current.busy) return null
        val command = if (delete) SavedQueryCommand.Delete else if (baseline == null) SavedQueryCommand.Create else SavedQueryCommand.Edit
        val draft = SavedQueryDraft(current.binding ?: return null, newQueryKey(), command, definition, baseline)
        if (retained.none { it.slot == draft.slot }) saveEdit(draft)
        return draft.slot
    }

    fun change(slot: String, definition: SavedViewDefinitionRequestDto) {
        val draft = _state.value.drafts.find { it.slot == slot } ?: return
        if (_state.value.canEdit(draft)) saveEdit(draft.copy(definition = definition, error = null))
    }

    private fun saveEdit(draft: SavedQueryDraft) {
        publish(draft)
        scope.launch(start = CoroutineStart.UNDISPATCHED) {
            withContext(NonCancellable) { persist(draft) }
        }
    }

    fun submit(slot: String) {
        val draft = _state.value.drafts.find { it.slot == slot } ?: return
        if (!_state.value.canSubmit(draft)) return
        val pending = draft.copy(phase = "unconfirmed", error = null)
        publish(pending)
        _state.value = _state.value.copy(busy = true)
        scope.launch {
            if (persist(pending)) {
                val result = repository.submit(pending)
                val error = result.exceptionOrNull()
                val rejected = (error as? RepositoryException)?.errorCode in setOf(
                    "invalid_request", "state_conflict", "saved_view_conflict", "saved_view_tag_repair_required", "saved_view_not_found")
                val next = result.getOrNull() ?: pending.copy(phase = if (rejected) "rejected" else "unconfirmed", error = error?.message)
                persist(next, publishSaved = true)
            }
            _state.value = _state.value.copy(busy = false)
        }
    }

    fun retrySave(slot: String) {
        val draft = _state.value.drafts.find { it.slot == slot } ?: return
        if (!_state.value.busy) saveEdit(draft)
    }

    fun review(slot: String) {
        val current = _state.value
        val draft = current.drafts.find { it.slot == slot } ?: return
        val binding = current.binding ?: return
        if (!current.ready || !current.canModify || current.busy || !draft.binding.sameReferenceOwner(binding)) return
        if (draft.binding == binding && draft.phase !in setOf("editing", "rejected")) return
        _state.value = current.copy(busy = true)
        scope.launch {
            when {
                draft.binding != binding -> persist(draft.copy(binding = binding, error = null), publishSaved = true)
                draft.baseline == null -> persist(draft.copy(key = newQueryKey(), phase = "editing", error = null), publishSaved = true)
                else -> repository.read(binding, draft.baseline.publicId).onSuccess { latest ->
                    // Read the current OCC token; the user's raw fields remain unchanged. No command is sent.
                    persist(draft.copy(baseline = latest, key = newQueryKey(), phase = "editing", error = null), publishSaved = true)
                }.onFailure { persist(draft.copy(error = it.message), publishSaved = true) }
            }
            _state.value = _state.value.copy(busy = false)
        }
    }

    fun acknowledge(slot: String) {
        val current = _state.value
        val draft = current.drafts.find { it.slot == slot } ?: return
        if (current.busy || draft.phase != "accepted" || current.binding != draft.binding) return
        _state.value = current.copy(busy = true)
        scope.launch {
            writes.withLock {
                repository.acknowledge(draft).onSuccess {
                    retained = retained.filterNot { it.key == draft.key }
                    publish()
                    if (_state.value.binding == draft.binding) onAccepted()
                }.onFailure { _state.value = _state.value.copy(error = UiText.res(R.string.saved_query_input_save_failed)) }
            }
            _state.value = _state.value.copy(busy = false)
        }
    }

    private suspend fun persist(draft: SavedQueryDraft, publishSaved: Boolean = false): Boolean = writes.withLock {
        val result = repository.saveDraft(draft)
        _state.value = _state.value.copy(error = if (result.isFailure) UiText.res(R.string.saved_query_input_save_failed) else null)
        if (result.isSuccess && publishSaved) publish(draft)
        result.isSuccess
    }
}

private fun newQueryKey() = UUID.randomUUID().toString()
