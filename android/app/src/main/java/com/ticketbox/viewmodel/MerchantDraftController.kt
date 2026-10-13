package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.domain.model.UiText
import com.ticketbox.domain.model.MerchantCatalog
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.MerchantDraft
import com.ticketbox.data.repository.MerchantDraftKind
import com.ticketbox.data.repository.MerchantRepository
import com.ticketbox.data.repository.RepositoryException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.util.UUID

/** Retains each original merchant command; dialogs own navigation only. */
class MerchantDraftController(
    private val repository: MerchantRepository,
    private val scope: CoroutineScope,
    private val onFailure: (MerchantDraft, Throwable) -> Unit = { _, _ -> },
    private val onCatalogRead: (List<MerchantCatalog>) -> Unit = {},
    private val onAccepted: (MerchantDraft) -> Unit,
) {
    private val owner = repository.captureBinding()
    private var access: LedgerAccessContext? = null
    private var retained: List<MerchantDraft> = emptyList()
    private val writes = Mutex()
    private val _state = MutableStateFlow(MerchantDraftState())
    val state = _state.asStateFlow()

    init {
        scope.launch { repository.observeAccess().collect { access = it; publish() } }
        reload()
    }

    fun reload() {
        val original = owner ?: return
        if (_state.value.ready || _state.value.busy) return
        _state.value = _state.value.copy(busy = true, error = null)
        scope.launch {
            repository.readMerchantDrafts(original).onSuccess { retained = it; _state.value = _state.value.copy(ready = true) }
                .onFailure { _state.value = _state.value.copy(error = UiText.res(R.string.merchant_creation_read_failed)) }
            _state.value = _state.value.copy(busy = false)
            publish()
        }
    }

    private fun publish(changes: List<MerchantDraft> = emptyList()) {
        if (changes.isNotEmpty()) {
            val slots = changes.map { it.slot }.toSet()
            retained = retained.filterNot { it.slot in slots } + changes
        }
        val current = access
        val sameOwner = current != null && owner?.sameReferenceOwner(current.binding) == true
        _state.value = _state.value.copy(binding = current?.binding,
            drafts = if (sameOwner) retained else emptyList(), canModify = current?.canModify == true && sameOwner)
    }

    fun edit(kind: MerchantDraftKind, name: String, canonical: String = "", alias: String = "") {
        val current = _state.value
        if (!kind.isCreation || !current.canEdit(kind)) return
        val draft = current.draft(kind) ?: MerchantDraft(current.binding ?: return, kind, newKey())
        saveEdit(draft.copy(displayName = name, canonicalMerchant = canonical, alias = alias, error = null))
    }

    fun begin(kind: MerchantDraftKind, source: MerchantCatalog, target: MerchantCatalog? = null) {
        val current = _state.value
        if (kind.isCreation || !current.ready || !current.canModify || current.busy || source.isMerged ||
            current.draft(kind, source.publicId) != null) return
        saveEdit(MerchantDraft(current.binding ?: return, kind, newKey(), source = source,
            displayName = source.displayName, nextStatus = if (source.isActive) "hidden" else "active", target = target,
            parentRenameKey = if (target != null) current.draft(MerchantDraftKind.Rename, source.publicId)?.key else null))
    }

    fun change(draft: MerchantDraft) {
        val original = _state.value.drafts.find { it.slot == draft.slot && it.key == draft.key } ?: return
        if (!_state.value.canEdit(original)) return
        val independentRename = original.displayName != draft.displayName && retained.any { it.parentRenameKey == original.key }
        saveEdit(original.copy(key = if (independentRename) newKey() else original.key,
            displayName = draft.displayName, target = draft.target, aliasPolicy = draft.aliasPolicy,
            targetUnavailable = original.targetUnavailable && original.target?.publicId == draft.target?.publicId, error = null))
    }

    private fun saveEdit(draft: MerchantDraft) {
        publish(listOf(draft))
        // Finish the queued Room write even when leaving the library cancels its ViewModel. No HTTP runs here.
        scope.launch(start = CoroutineStart.UNDISPATCHED) {
            withContext(NonCancellable) { persist(listOf(draft)) }
        }
    }

    fun submit(kind: MerchantDraftKind, sourceId: String? = null) {
        val current = _state.value
        val draft = current.draft(kind, sourceId) ?: return
        if (!current.canSubmit(draft)) return
        val pending = draft.copy(phase = "unconfirmed", error = null)
        publish(listOf(pending))
        _state.value = _state.value.copy(busy = true)
        scope.launch {
            if (persist(listOf(pending))) {
                val result = repository.submitDraft(pending)
                val error = result.exceptionOrNull()
                val rejected = (error as? RepositoryException)?.errorCode in setOf(
                    "invalid_request", "state_conflict", "merchant_alias_conflict", "idempotency_key_reused", "not_found")
                val next = result.getOrNull() ?: pending.copy(phase = if (rejected) "rejected" else "unconfirmed", error = error?.message)
                persist(listOf(next), publishSaved = true)
                _state.value = _state.value.copy(busy = false)
                if (error != null) onFailure(next, error)
            }
            _state.value = _state.value.copy(busy = false)
        }
    }

    fun review(kind: MerchantDraftKind, sourceId: String? = null) {
        val current = _state.value
        val draft = current.draft(kind, sourceId) ?: return
        if (!current.canReview(draft)) return
        val binding = current.binding ?: return
        if (!draft.binding.sameReferenceOwner(binding)) return
        _state.value = current.copy(busy = true)
        scope.launch {
            when {
                // Re-authentication does not create a new command or replace an unknown original result.
                draft.binding != binding -> persist(listOf(draft.copy(binding = binding, error = null)), publishSaved = true)
                kind.isCreation -> if (draft.phase == "rejected") persist(listOf(draft.copy(key = newKey(), phase = "editing", error = null)), publishSaved = true)
                else -> reviewCatalog(draft)
            }
            _state.value = _state.value.copy(busy = false)
        }
    }

    private suspend fun reviewCatalog(draft: MerchantDraft) {
        repository.merchantCatalog(expectedBinding = draft.binding).onSuccess { catalog ->
            val reviewed = draft.reviewedAgainst(catalog)
            val parent = retained.find { it.key == draft.parentRenameKey && it.phase in setOf("editing", "rejected") }
                ?.reviewedAgainst(catalog)
            val batch = listOfNotNull(reviewed.copy(parentRenameKey = parent?.key ?: reviewed.parentRenameKey), parent)
            if (persist(batch, publishSaved = true)) onCatalogRead(catalog)
        }.onFailure { error ->
            persist(listOf(draft.copy(error = error.message)), publishSaved = true)
            onFailure(draft, error)
        }
    }

    /** The bound screen observed this first receipt; refresh queries instead of inserting the receipt into them. */
    fun acknowledge(kind: MerchantDraftKind, key: String) {
        val current = _state.value
        val draft = current.drafts.find { it.kind == kind && it.key == key } ?: return
        if (current.busy || draft.phase != "accepted" || draft.acceptedId == null || draft.binding != current.binding) return
        _state.value = current.copy(busy = true, error = null)
        scope.launch {
            writes.withLock {
                repository.acknowledgeMerchantDraft(draft).onSuccess {
                    retained = retained.filterNot { it.key == key || it.key == draft.parentRenameKey }
                    publish()
                    if (_state.value.binding == draft.binding) onAccepted(draft)
                }.onFailure { _state.value = _state.value.copy(error = UiText.res(if (kind.isCreation) R.string.merchant_creation_acknowledge_failed else R.string.merchant_command_acknowledge_failed)) }
            }
            _state.value = _state.value.copy(busy = false)
        }
    }

    private suspend fun persist(drafts: List<MerchantDraft>, publishSaved: Boolean = false): Boolean = writes.withLock {
        val saved = repository.saveMerchantDrafts(drafts)
        _state.value = _state.value.copy(error = if (saved.isFailure) UiText.res(R.string.merchant_creation_save_failed) else null)
        if (saved.isSuccess && publishSaved) publish(drafts)
        saved.isSuccess
    }
}

private fun newKey() = UUID.randomUUID().toString()

private fun MerchantDraft.reviewedAgainst(catalog: List<MerchantCatalog>): MerchantDraft {
    val currentSource = catalog.find { it.publicId == source?.publicId && it.deletedAt == null && !it.isMerged }
    val currentTarget = catalog.find { it.publicId == target?.publicId && it.deletedAt == null && it.isActive }
    return copy(source = currentSource ?: source, target = currentTarget ?: target,
        sourceUnavailable = currentSource == null, targetUnavailable = target != null && currentTarget == null,
        key = if (phase == "rejected") newKey() else key, phase = "editing", error = null, reviewed = true)
}
