package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.domain.model.UiText
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.MerchantCreationDraft
import com.ticketbox.data.repository.MerchantCreationKind
import com.ticketbox.data.repository.MerchantRepository
import com.ticketbox.data.repository.RepositoryException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.util.UUID

data class MerchantCreationState(
    val drafts: List<MerchantCreationDraft> = emptyList(),
    val binding: LogicalSessionBinding? = null,
    val ready: Boolean = false,
    val canModify: Boolean = false,
    val busy: Boolean = false,
    val error: UiText? = null,
) {
    fun draft(kind: MerchantCreationKind) = drafts.firstOrNull { it.kind == kind }

    fun canEdit(kind: MerchantCreationKind): Boolean = ready && canModify && !busy &&
        (draft(kind) == null || draft(kind)?.let { it.binding == binding && it.phase == "editing" } == true)

    fun canSubmit(kind: MerchantCreationKind): Boolean {
        val original = draft(kind) ?: return false
        val filled = if (kind == MerchantCreationKind.Catalog) original.displayName.isNotBlank()
            else original.canonicalMerchant.isNotBlank() && original.alias.isNotBlank()
        return ready && canModify && !busy && original.binding == binding && filled &&
            original.phase in setOf("editing", "unconfirmed")
    }
}

/** The merchant screen owns editing; this controller retains the original command across screen and process exits. */
class MerchantCreationController(
    private val repository: MerchantRepository,
    private val scope: CoroutineScope,
    private val onAccepted: (MerchantCreationDraft) -> Unit,
) {
    private val owner = repository.captureBinding()
    private var access: LedgerAccessContext? = null
    private var retained: List<MerchantCreationDraft> = emptyList()
    private val writes = Mutex()
    private val _state = MutableStateFlow(MerchantCreationState())
    val state = _state.asStateFlow()

    init {
        scope.launch {
            repository.observeAccess().collect {
                access = it
                publish()
            }
        }
        reload()
    }

    fun reload() {
        val original = owner ?: return
        if (_state.value.ready || _state.value.busy) return
        _state.value = _state.value.copy(busy = true, error = null)
        scope.launch {
            repository.readCreationDrafts(original).onSuccess { retained = it; _state.value = _state.value.copy(ready = true) }
                .onFailure { _state.value = _state.value.copy(error = UiText.res(R.string.merchant_creation_read_failed)) }
            _state.value = _state.value.copy(busy = false)
            publish()
        }
    }

    private fun publish() {
        val current = access
        val sameOwner = current != null && owner?.sameReferenceOwner(current.binding) == true
        _state.value = _state.value.copy(binding = current?.binding,
            drafts = if (sameOwner) retained else emptyList(),
            canModify = current?.canModify == true && sameOwner)
    }

    fun edit(kind: MerchantCreationKind, name: String, canonical: String = "", alias: String = "") {
        val current = _state.value
        if (!current.canEdit(kind)) return
        val draft = current.draft(kind) ?: MerchantCreationDraft(current.binding ?: return, kind, UUID.randomUUID().toString())
        val changed = draft.copy(displayName = name, canonicalMerchant = canonical, alias = alias, error = null)
        replace(changed)
        scope.launch { writes.withLock { persist(changed) } }
    }

    fun submit(kind: MerchantCreationKind) {
        val current = _state.value
        val draft = current.draft(kind) ?: return
        if (!current.canSubmit(kind)) return
        val pending = draft.copy(phase = "unconfirmed", error = null)
        replace(pending)
        _state.value = _state.value.copy(busy = true)
        scope.launch {
            val stored = writes.withLock { persist(pending) }
            if (stored) {
                val result = repository.submitCreation(pending)
                val error = result.exceptionOrNull()
                val rejected = (error as? RepositoryException)?.errorCode in setOf(
                    "invalid_request", "state_conflict", "merchant_alias_conflict", "idempotency_key_reused")
                val next = result.getOrNull() ?: pending.copy(phase = if (rejected) "rejected" else "unconfirmed", error = error?.message)
                writes.withLock { if (persist(next)) replace(next) }
            }
            _state.value = _state.value.copy(busy = false)
        }
    }

    fun review(kind: MerchantCreationKind) {
        val current = _state.value
        val draft = current.draft(kind) ?: return
        if (!current.canModify || current.busy) return
        val binding = current.binding ?: return
        if (!draft.binding.sameReferenceOwner(binding)) return
        val reviewed = when {
            draft.binding != binding -> draft.copy(binding = binding, error = null)
            draft.phase == "rejected" -> draft.copy(key = UUID.randomUUID().toString(), phase = "editing", error = null)
            else -> return
        }
        _state.value = current.copy(busy = true)
        scope.launch {
            writes.withLock { if (persist(reviewed)) replace(reviewed) }
            _state.value = _state.value.copy(busy = false)
        }
    }

    /** Called only after the bound screen has observed the accepted receipt. Never insert it into the current query. */
    fun acknowledge(kind: MerchantCreationKind, key: String) {
        val current = _state.value
        val draft = current.draft(kind) ?: return
        if (current.busy || draft.key != key || draft.phase != "accepted" || draft.acceptedId == null || draft.binding != current.binding) return
        _state.value = current.copy(busy = true, error = null)
        scope.launch {
            writes.withLock {
                repository.removeCreationDraft(draft).onSuccess {
                    retained = retained.filterNot { it.key == key }
                    publish()
                    if (_state.value.binding == draft.binding) onAccepted(draft)
                }.onFailure { _state.value = _state.value.copy(error = UiText.res(R.string.merchant_creation_acknowledge_failed)) }
            }
            _state.value = _state.value.copy(busy = false)
        }
    }

    private fun replace(draft: MerchantCreationDraft) {
        retained = retained.filterNot { it.kind == draft.kind } + draft
        publish()
    }

    private suspend fun persist(draft: MerchantCreationDraft): Boolean {
        val saved = repository.saveCreationDraft(draft)
        _state.value = _state.value.copy(error = if (saved.isFailure) UiText.res(R.string.merchant_creation_save_failed) else null)
        return saved.isSuccess
    }
}
