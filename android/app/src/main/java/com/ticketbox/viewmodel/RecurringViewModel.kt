package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.RecurringActions
import com.ticketbox.data.repository.RecurringPendingIntent
import com.ticketbox.data.repository.RecurringSaveOutcome
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.RecurringCandidate
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.util.UUID

data class RecurringUiState(
    val loading: Boolean = false,
    val message: UiText? = null,
    val messageTone: MessageTone = MessageTone.Neutral,
    val items: List<RecurringItem> = emptyList(),
    val candidates: List<RecurringCandidate> = emptyList(),
    val pendingIntents: List<RecurringPendingIntent> = emptyList(),
    val duplicateConflict: RecurringDuplicateConflict? = null,
    val itemsLoadState: RecurringListLoadState = RecurringListLoadState.Unknown,
    val candidatesLoadState: RecurringListLoadState = RecurringListLoadState.Unknown,
    val canModify: Boolean = true,
    val manualSaveFeedback: RecurringManualSaveFeedback? = null,
    val editorEpoch: Long = 0,
    val editorRuntimeId: String = "",
) {
    val manualSaveInFlight: Boolean
        get() = manualSaveFeedback?.settlement == RecurringManualSaveSettlement.InFlight
}

data class RecurringDuplicateConflict(
    val publicId: String,
    val status: String,
)

enum class RecurringListLoadState {
    Unknown,
    Loading,
    Loaded,
    Failed,
}

class RecurringViewModel(
    private val repository: RecurringActions,
    private val onDataChanged: () -> Unit = {},
) : ViewModel() {
    private val editorRuntimeId = UUID.randomUUID().toString()
    private val _uiState = MutableStateFlow(
        RecurringUiState(canModify = false, editorRuntimeId = editorRuntimeId),
    )
    val uiState: StateFlow<RecurringUiState> = _uiState.asStateFlow()
    private var requestGeneration = 0
    private var refreshGeneration = 0
    private var activeBinding: LogicalSessionBinding? = null
    private var activeCanModify = false
    private var observedPendingKeys: Set<String>? = null
    private var manualSaveSequence = 0L
    private var activeManualAttemptId: Long? = null
    private var editorEpoch = 0L

    init {
        viewModelScope.launch {
            repository.observeActiveLedgerAccess()
                .distinctUntilChanged()
                .collect { access ->
                    val nextBinding = access?.binding
                    val bindingChanged = activeBinding != nextBinding
                    activeCanModify = access?.canModify ?: false
                    if (!bindingChanged) {
                        _uiState.update { it.copy(canModify = activeCanModify) }
                        return@collect
                    }
                    activeBinding = nextBinding
                    requestGeneration += 1
                    refreshGeneration += 1
                    activeManualAttemptId = null
                    editorEpoch += 1
                    _uiState.value = RecurringUiState(
                        loading = access != null,
                        itemsLoadState = if (access == null) {
                            RecurringListLoadState.Unknown
                        } else {
                            RecurringListLoadState.Loading
                        },
                        candidatesLoadState = if (access == null) {
                            RecurringListLoadState.Unknown
                        } else {
                            RecurringListLoadState.Loading
                        },
                        canModify = access?.canModify ?: false,
                        editorEpoch = editorEpoch,
                        editorRuntimeId = editorRuntimeId,
                    )
                    if (access != null) refresh()
                }
        }
        viewModelScope.launch {
            repository.observePendingIntents()
                .collect { intents ->
                    val currentKeys = intents.mapTo(mutableSetOf(), RecurringPendingIntent::idempotencyKey)
                    val resolved = observedPendingKeys?.minus(currentKeys).orEmpty().isNotEmpty()
                    observedPendingKeys = currentKeys
                    _uiState.update { it.copy(pendingIntents = intents) }
                    if (resolved && activeBinding != null) refresh()
                }
        }
    }

    fun refresh() {
        refreshInternal(preserveMutationFeedback = false)
    }

    private fun refreshInternal(preserveMutationFeedback: Boolean) {
        val binding = activeBinding ?: return
        val generation = requestGeneration
        val refresh = ++refreshGeneration
        viewModelScope.launch {
            _uiState.update { state ->
                val keepFeedback = state.shouldKeepMutationFeedback(preserveMutationFeedback)
                state.copy(
                    loading = true,
                    itemsLoadState = RecurringListLoadState.Loading,
                    candidatesLoadState = RecurringListLoadState.Loading,
                    message = if (keepFeedback) state.message else null,
                    messageTone = if (keepFeedback) {
                        state.messageTone
                    } else {
                        MessageTone.Neutral
                    },
                    canModify = activeCanModify,
                )
            }
            val itemsResult = repository.items(binding, includeArchived = true)
            val candidatesResult = repository.candidates(binding)
            if (requestGeneration != generation || refreshGeneration != refresh) return@launch
            val message = listOf(itemsResult, candidatesResult)
                .firstOrNull { it.isFailure }
                ?.exceptionOrNull()
                ?.toUiText(R.string.recurring_message_action_failed)
            _uiState.update { state ->
                val keepFeedback = state.shouldKeepMutationFeedback(preserveMutationFeedback)
                state.copy(
                    loading = false,
                    message = if (keepFeedback) state.message else message,
                    messageTone = if (keepFeedback) {
                        state.messageTone
                    } else if (message == null) {
                        MessageTone.Neutral
                    } else {
                        MessageTone.Danger
                    },
                    items = itemsResult.getOrElse { state.items },
                    candidates = candidatesResult.getOrElse { state.candidates },
                    itemsLoadState = itemsResult.toRecurringListLoadState(),
                    candidatesLoadState = candidatesResult.toRecurringListLoadState(),
                    canModify = activeCanModify,
                )
            }
        }
    }

    fun confirmCandidate(candidate: RecurringCandidate) {
        if (candidate !in _uiState.value.candidates) {
            _uiState.update {
                it.copy(
                    message = UiText.res(R.string.recurring_message_candidate_expired),
                    messageTone = MessageTone.Info,
                )
            }
            return
        }
        mutate(
            action = { binding -> repository.confirmCandidate(binding, candidate) },
            onSuccessState = { state, item ->
                state.copy(
                    items = state.items.withRecurringItem(item),
                    candidates = state.candidates.filterNot { it == candidate },
                )
            },
        )
    }

    fun pause(publicId: String, expectedRowVersion: Long) {
        mutate(action = { binding -> repository.pause(binding, publicId, expectedRowVersion) })
    }

    fun resume(publicId: String, expectedRowVersion: Long) {
        mutate(action = { binding -> repository.resume(binding, publicId, expectedRowVersion) })
    }

    fun archive(publicId: String) {
        mutate(action = { binding -> repository.archive(binding, publicId) })
    }

    fun restore(publicId: String, expectedRowVersion: Long) {
        mutate(action = { binding -> repository.restore(binding, publicId, expectedRowVersion) })
    }

    fun saveManual(command: RecurringManualSaveCommand): Long {
        activeManualAttemptId?.let { return it }
        val attemptId = ++manualSaveSequence
        val binding = manualBindingOrReject(attemptId) ?: return attemptId
        activeManualAttemptId = attemptId
        val generation = requestGeneration
        refreshGeneration += 1
        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    loading = true,
                    message = null,
                    messageTone = MessageTone.Neutral,
                    duplicateConflict = null,
                    manualSaveFeedback = RecurringManualSaveFeedback(
                        attemptId = attemptId,
                        settlement = RecurringManualSaveSettlement.InFlight,
                    ),
                )
            }
            val result = when (command) {
                is RecurringManualSaveCommand.Create ->
                    repository.createAllowingOffline(binding, command.draft)
                is RecurringManualSaveCommand.Edit ->
                    repository.updateAllowingOffline(binding, command.baseline, command.patch)
            }
            if (requestGeneration != generation) {
                if (activeManualAttemptId == attemptId) activeManualAttemptId = null
                return@launch
            }
            if (activeManualAttemptId == attemptId) activeManualAttemptId = null
            val displacedOwnerRefresh = _uiState.value.ownerRefreshInFlight
            refreshGeneration += 1
            result.fold(
                onSuccess = { outcome ->
                    _uiState.update { state ->
                        state.withManualSaveOutcome(outcome, activeCanModify, attemptId)
                    }
                    outcome.finishManualSave(displacedOwnerRefresh, onDataChanged) {
                        refreshInternal(preserveMutationFeedback = true)
                    }
                },
                onFailure = { error ->
                    handleMutationFailure(
                        error = error,
                        manualAttemptId = attemptId,
                        displacedOwnerRefresh = displacedOwnerRefresh,
                    )
                },
            )
        }
        return attemptId
    }

    private fun manualBindingOrReject(attemptId: Long): LogicalSessionBinding? {
        val binding = activeBinding
        if (binding != null && repository.canModifyLedger()) return binding
        val message = UiText.res(R.string.common_readonly_ledger)
        _uiState.update {
            it.copy(
                message = message,
                messageTone = MessageTone.Danger,
                canModify = false,
                manualSaveFeedback = RecurringManualSaveFeedback(
                    attemptId = attemptId,
                    settlement = RecurringManualSaveSettlement.Failed,
                    message = message,
                ),
            )
        }
        return null
    }

    private fun mutate(
        action: suspend (LogicalSessionBinding) -> Result<RecurringItem>,
        onSuccessState: (RecurringUiState, RecurringItem) -> RecurringUiState = { state, item ->
            state.copy(items = state.items.withRecurringItem(item))
        },
    ) {
        val binding = activeBinding
        if (binding == null || !repository.canModifyLedger()) {
            _uiState.update {
                it.copy(
                    message = UiText.res(R.string.common_readonly_ledger),
                    messageTone = MessageTone.Danger,
                    canModify = false,
                )
            }
            return
        }
        val generation = requestGeneration
        refreshGeneration += 1
        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    loading = true,
                    message = null,
                    messageTone = MessageTone.Neutral,
                    duplicateConflict = null,
                )
            }
            val result = action(binding)
            if (requestGeneration != generation) return@launch
            val displacedOwnerRefresh = _uiState.value.ownerRefreshInFlight
            refreshGeneration += 1
            result.fold(
                onSuccess = { item ->
                    _uiState.update { state ->
                        onSuccessState(
                            state.copy(
                                loading = false,
                                message = UiText.res(R.string.recurring_message_updated),
                                messageTone = MessageTone.Success,
                                duplicateConflict = null,
                                canModify = activeCanModify,
                            ),
                            item,
                        )
                    }
                    onDataChanged()
                    refreshInternal(preserveMutationFeedback = true)
                },
                onFailure = { error ->
                    handleMutationFailure(
                        error = error,
                        displacedOwnerRefresh = displacedOwnerRefresh,
                    )
                },
            )
        }
    }

    private fun handleMutationFailure(
        error: Throwable,
        manualAttemptId: Long? = null,
        displacedOwnerRefresh: Boolean = false,
    ) {
        val conflict = error.toRecurringDuplicateConflict()
        val repositoryErrorCode = (error as? RepositoryException)?.errorCode
        val stateConflict = repositoryErrorCode == "state_conflict"
        val refreshOwner = conflict != null || stateConflict
        val message = error.toUiText(R.string.recurring_message_action_failed)
        _uiState.update {
            it.copy(
                loading = false,
                message = message,
                messageTone = MessageTone.Danger,
                duplicateConflict = conflict,
                itemsLoadState = if (refreshOwner) {
                    RecurringListLoadState.Loading
                } else {
                    it.itemsLoadState
                },
                canModify = activeCanModify,
                manualSaveFeedback = manualAttemptId?.let { attemptId ->
                    RecurringManualSaveFeedback(
                        attemptId = attemptId,
                        settlement = RecurringManualSaveSettlement.Failed,
                        message = message,
                        requiresOwnerReload = stateConflict,
                    )
                } ?: it.manualSaveFeedback,
            )
        }
        if (refreshOwner || displacedOwnerRefresh) {
            // A conflict requires a fresh owner; a displaced Loading owner
            // requires a replacement. Stable Loaded/Empty owners are left
            // untouched so an offline failure cannot manufacture LoadFailed.
            refreshInternal(preserveMutationFeedback = true)
        }
    }
}

private val RecurringUiState.ownerRefreshInFlight: Boolean
    get() = itemsLoadState == RecurringListLoadState.Loading ||
        candidatesLoadState == RecurringListLoadState.Loading

private fun RecurringSaveOutcome.finishManualSave(
    displacedOwnerRefresh: Boolean,
    onSynced: () -> Unit,
    refreshOwner: () -> Unit,
) {
    if (this is RecurringSaveOutcome.Synced) onSynced()
    if (this is RecurringSaveOutcome.Synced || displacedOwnerRefresh) refreshOwner()
}

private fun RecurringUiState.withManualSaveOutcome(
    outcome: RecurringSaveOutcome,
    canModify: Boolean,
    attemptId: Long,
): RecurringUiState = when (outcome) {
    is RecurringSaveOutcome.Synced -> copy(
        loading = false,
        items = items.withRecurringItem(outcome.item),
        message = UiText.res(R.string.recurring_message_updated),
        messageTone = MessageTone.Success,
        duplicateConflict = null,
        canModify = canModify,
        manualSaveFeedback = RecurringManualSaveFeedback(
            attemptId = attemptId,
            settlement = RecurringManualSaveSettlement.Accepted,
            message = UiText.res(R.string.recurring_message_updated),
        ),
    )
    is RecurringSaveOutcome.Queued -> copy(
        loading = false,
        pendingIntents = pendingIntents.withPendingIntent(outcome.intent),
        message = UiText.res(R.string.recurring_message_queued),
        messageTone = MessageTone.Info,
        duplicateConflict = null,
        canModify = canModify,
        manualSaveFeedback = RecurringManualSaveFeedback(
            attemptId = attemptId,
            settlement = RecurringManualSaveSettlement.Accepted,
            message = UiText.res(R.string.recurring_message_queued),
        ),
    )
}

private fun RecurringUiState.shouldKeepMutationFeedback(explicit: Boolean): Boolean =
    explicit || duplicateConflict != null

private fun <T> Result<T>.toRecurringListLoadState(): RecurringListLoadState =
    if (isSuccess) RecurringListLoadState.Loaded else RecurringListLoadState.Failed

private fun List<RecurringItem>.withRecurringItem(item: RecurringItem): List<RecurringItem> =
    if (any { it.publicId == item.publicId }) {
        map { existing -> if (existing.publicId == item.publicId) item else existing }
    } else {
        listOf(item) + this
    }

private fun List<RecurringPendingIntent>.withPendingIntent(
    intent: RecurringPendingIntent,
): List<RecurringPendingIntent> =
    if (any { it.idempotencyKey == intent.idempotencyKey }) {
        map { existing -> if (existing.idempotencyKey == intent.idempotencyKey) intent else existing }
    } else {
        this + intent
    }

private fun Throwable.toRecurringDuplicateConflict(): RecurringDuplicateConflict? {
    val repositoryError = this as? RepositoryException ?: return null
    if (
        repositoryError.errorCode != "recurring_item_conflict" &&
        repositoryError.errorCode != "recurring_item_archived"
    ) return null
    val publicId = repositoryError.conflictRecurringPublicId?.trim()?.takeIf(String::isNotEmpty)
        ?: return null
    val status = repositoryError.conflictRecurringStatus?.trim()
        ?.takeIf { it == "active" || it == "paused" || it == "archived" }
        ?: return null
    return RecurringDuplicateConflict(publicId = publicId, status = status)
}
