package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.createSavedStateHandle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.CreationExtras
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.ReferenceCreationActions
import com.ticketbox.data.repository.RepositoryException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.util.UUID

data class ReferenceCreationUiState(
    val binding: LogicalSessionBinding? = null,
    val draft: ReferenceCreationDraft? = null,
    val canModify: Boolean = false,
    val bindingChanged: Boolean = false,
    val canReviewIdentity: Boolean = false,
    val busy: Boolean = false,
)

/** One library creation task per owner/kind, retained by the existing MAIN saved-state owner. */
class ReferenceCreationViewModel(
    private val repository: ReferenceCreationActions,
    savedStateHandle: SavedStateHandle = SavedStateHandle(),
) : ViewModel() {
    private val store = ReferenceCreationDraftStore(savedStateHandle)
    private var access: LedgerAccessContext? = null
    private val inFlight = mutableSetOf<String>()
    private val _state = MutableStateFlow(ReferenceCreationUiState())
    val state = _state.asStateFlow()

    init {
        viewModelScope.launch {
            repository.observeAccess().collect { access = it; publish() }
        }
    }

    fun open() {
        val current = _state.value
        val binding = current.binding ?: return
        if (current.draft == null && current.canModify) {
            store.write(ReferenceCreationDraft(binding, UUID.randomUUID().toString()))
            publish()
        }
    }

    fun updateName(name: String) {
        val current = _state.value
        val draft = current.draft ?: return
        if (!current.canModify || current.busy || draft.phase != "editing") return
        store.write(draft.copy(name = name, error = null))
        publish()
    }

    fun submit() {
        val current = _state.value
        val draft = current.draft ?: return
        if (!current.canModify || current.busy || draft.phase in setOf("rejected", "accepted") || draft.name.isBlank()) return
        val pending = draft.copy(phase = "unconfirmed", error = null)
        store.write(pending)
        inFlight += draft.key
        publish()
        viewModelScope.launch {
            val result = repository.create(draft.binding, draft.name, draft.key)
            val error = result.exceptionOrNull()
            val rejected = (error as? RepositoryException)?.errorCode in
                setOf("invalid_request", "reference_name_conflict", "idempotency_key_reused")
            store.write(pending.copy(phase = when { result.isSuccess -> "accepted"; rejected -> "rejected"; else -> "unconfirmed" },
                receipt = result.getOrNull(), error = error?.message))
            inFlight -= draft.key
            publish()
        }
    }

    /** Only a definite refusal permits a new intent; uncertain replies must replay the original. */
    fun reviewRejected() {
        val current = _state.value
        val draft = current.draft ?: return
        if (!current.canModify || current.busy || draft.phase != "rejected") return
        store.remove(draft.key)
        store.write(draft.copy(key = UUID.randomUUID().toString(), phase = "editing", error = null))
        publish()
    }

    /** Explicit reauthentication review changes no account/ledger/server identity, name or command key. */
    fun reviewIdentity() {
        val current = _state.value
        if (!current.canReviewIdentity || current.busy) return
        val draft = current.draft ?: return
        store.write(draft.copy(binding = requireNotNull(current.binding)))
        publish()
    }

    fun consumeReceipt(key: String) {
        val draft = _state.value.draft ?: return
        if (draft.key != key || draft.receipt == null || _state.value.bindingChanged) return
        store.remove(key)
        publish()
    }

    private fun publish() {
        val binding = access?.binding
        val draft = binding?.let(store::read)
        val changed = draft != null && draft.binding != binding
        _state.value = ReferenceCreationUiState(binding, draft,
            canModify = access?.canModify == true && !changed,
            bindingChanged = changed, canReviewIdentity = changed && access?.canModify == true,
            busy = draft?.key in inFlight)
    }
}

fun referenceCreationViewModelFactory(repository: ReferenceCreationActions): ViewModelProvider.Factory =
    object : ViewModelProvider.Factory {
        override fun <T : ViewModel> create(modelClass: Class<T>): T = requireNotNull(modelClass.cast(ReferenceCreationViewModel(repository)))
        override fun <T : ViewModel> create(modelClass: Class<T>, extras: CreationExtras): T =
            requireNotNull(modelClass.cast(ReferenceCreationViewModel(repository, extras.createSavedStateHandle())))
    }
