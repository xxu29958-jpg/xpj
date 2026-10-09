package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.remote.dto.OriginalHealthDto
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.OriginalAttachmentActions
import com.ticketbox.data.repository.PendingOriginalCommand
import com.ticketbox.data.repository.OriginalSelectionDraft
import com.ticketbox.data.repository.OriginalSubmission
import com.ticketbox.data.repository.originalPayloadAdapter
import com.ticketbox.data.repository.logNetworkWarning
import com.ticketbox.domain.model.ProtectedImage
import com.ticketbox.domain.model.UiText
import com.ticketbox.upload.PreparedUploadImage
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

class OriginalImageSelection(val source: PreparedUploadImage) {
    val preview = ProtectedImage(source.bytes, source.contentType)
}

data class OriginalAttachmentUiState(
    val access: LedgerAccessContext? = null,
    val health: OriginalHealthDto? = null,
    val checking: Boolean = false,
    val stale: Boolean = true,
    val image: ProtectedImage? = null,
    val imageLoading: Boolean = false,
    val reviewedDigest: String? = null,
    val commands: List<PendingOriginalCommand> = emptyList(),
    val busy: Boolean = false,
    val selectedSource: Boolean = false,
    val selectionLoaded: Boolean = false,
    val selectionDraft: OriginalSelectionDraft? = null,
    val selection: OriginalImageSelection? = null,
    val selectionDisplayed: Boolean = false,
    val selectionConfirmed: Boolean = false,
    val localIntent: Boolean = false,
    val localIntentBound: Boolean = false,
    val message: UiText? = null,
    val deliveredRevision: Int = 0,
) {
    val canReadOriginal: Boolean get() = health?.state !in setOf("none", "cleaned", "missing", "corrupt")
    val canSubmit: Boolean get() = selectionLoaded && access?.canModify == true && health != null && !stale && !checking && !busy &&
        !localIntent && commands.none { !it.delivered }
    val canVerify: Boolean get() = canSubmit && health?.state == "unverified" &&
        reviewedDigest != null && reviewedDigest == image?.originalSha256
    val canConfirmSelection: Boolean get() = localIntentBound && access?.canModify == true && !busy &&
        selectionDraft != null && selection != null && selectionDisplayed && selectionConfirmed
    val canResumeSelection: Boolean get() = !busy && (!selectionLoaded || localIntentBound && (selectedSource || access?.canModify == true))
    val selectionOperation: String? get() = when {
        localIntent -> null
        health?.state == "none" && health.cleanup == null && health.cleanupError == null -> "attach_original"
        health?.expectedSha256 != null && health.state in setOf("missing", "corrupt", "cleaned", "unreadable") -> "replenish_original"
        else -> null
    }
}

/** Ephemeral detail presentation; the existing UploadIntentRepository/Room owns every submitted command. */
class OriginalAttachmentViewModel(
    internal val expenseId: Long,
    internal val originals: OriginalAttachmentActions,
    private val fetchImage: suspend (Long) -> Result<ProtectedImage>,
    internal val saved: SavedStateHandle,
) : ViewModel() {
    internal fun restoredState() = OriginalAttachmentUiState(selectedSource = saved.get<String>("original_uri") != null,
        localIntent = saved.get<String>("original_payload") != null)
    internal val mutableState = MutableStateFlow(restoredState())
    val state = mutableState.asStateFlow()
    private var readGeneration = 0L
    private var imageGeneration = 0L
    private var seenReceipts: Set<Long>? = null

    init {
        viewModelScope.launch {
            originals.observeOriginalCommands().collect { observation ->
                if (observation.access?.binding != originals.currentOriginalBinding()) return@collect
                val bindingChanged = mutableState.value.access?.binding != observation.access?.binding
                val commands = observation.commands.filter { it.row.targetId == "expense:$expenseId" }
                val delivered = commands.filter { it.delivered }.map { it.row.id }.toSet()
                val newlyDelivered = seenReceipts?.let { delivered - it }.orEmpty()
                if (bindingChanged) {
                    readGeneration++
                    imageGeneration++
                    mutableState.value = restoredState()
                }
                mutableState.update { it.copy(access = observation.access, commands = commands, localIntentBound = savedOriginalBinding() == observation.access?.binding) }
                reconcileSubmittedSelection()
                if (bindingChanged && observation.access != null) restoreOriginalSelection(observation.access.binding)
                if (bindingChanged || newlyDelivered.isNotEmpty()) {
                    mutableState.update { it.copy(image = null, reviewedDigest = null, deliveredRevision = it.deliveredRevision + if (newlyDelivered.isEmpty()) 0 else 1) }
                    refresh(preserveMessage = true)
                }
                seenReceipts = delivered
            }
        }
    }

    private fun savedOriginalBinding() = saved.get<String>("original_payload")?.let {
        runCatching { com.ticketbox.data.repository.originalPayloadAdapter.fromJson(it)?.origin }.getOrNull()
    }

    fun refresh(preserveMessage: Boolean = false) {
        val binding = mutableState.value.access?.binding ?: return
        val generation = ++readGeneration
        mutableState.update { it.copy(checking = true, stale = true, message = if (preserveMessage) it.message else null) }
        viewModelScope.launch {
            val result = originals.fetchOriginalHealth(expenseId)
            if (binding != originals.currentOriginalBinding() || generation != readGeneration) return@launch
            result.onSuccess { health ->
                if (health.expenseId == expenseId) mutableState.update { it.copy(health = health, checking = false, stale = false) }
                else mutableState.update { it.copy(checking = false, message = UiText.res(R.string.original_health_failed)) }
            }.onFailure { error ->
                mutableState.update { it.copy(checking = false, message = error.toUiText(R.string.original_health_failed)) }
            }
        }
    }

    fun loadImage() {
        val binding = mutableState.value.access?.binding ?: return
        if (mutableState.value.imageLoading) return
        val generation = ++imageGeneration
        mutableState.update { it.copy(imageLoading = true, image = null, reviewedDigest = null, message = null) }
        viewModelScope.launch {
            val result = fetchImage(expenseId)
            if (binding != originals.currentOriginalBinding() || generation != imageGeneration) return@launch
            result.onSuccess { image -> mutableState.update { it.copy(image = image, imageLoading = false) } }
                .onFailure { error ->
                    mutableState.update { it.copy(imageLoading = false, message = error.toUiText(R.string.original_image_failed)) }
                    refresh(preserveMessage = true)
                }
        }
    }

    /** Called after actual image decoding/rendering, never by health or thumbnail reads. */
    fun imageDisplayed(image: ProtectedImage) {
        if (mutableState.value.image !== image || mutableState.value.access?.binding != originals.currentOriginalBinding()) return
        mutableState.update { it.copy(reviewedDigest = image.originalSha256) }
    }

    fun selectedImageDisplayed(image: ProtectedImage) {
        if (state.value.selection?.preview !== image || !state.value.localIntentBound) return
        mutableState.update { it.copy(selectionDisplayed = true) }
    }

    internal fun loadSelectedImage(uri: String, binding: LogicalSessionBinding, prepare: suspend (String) -> PreparedUploadImage?) {
        val payload = saved.get<String>("original_payload")?.let(originalPayloadAdapter::fromJson) ?: return
        val key = saved.get<String>("original_key") ?: return
        mutableState.update { it.copy(busy = true, message = null) }
        viewModelScope.launch {
            try {
                val source = requireNotNull(prepare(uri))
                val result = originals.originalSelections.retainOriginalSelection(OriginalSubmission(key, payload) { source })
                if (binding != originals.currentOriginalBinding() || saved.get<String>("original_uri") != uri) return@launch
                mutableState.update { it.copy(selection = OriginalImageSelection(source), selectionDraft = result.getOrNull(),
                    message = result.exceptionOrNull()?.toUiText(R.string.original_selection_save_failed)) }
            } catch (cancelled: CancellationException) { throw cancelled }
            catch (error: Exception) {
                logNetworkWarning("operation=OriginalSelection source read failed", error)
                if (binding == originals.currentOriginalBinding())
                    mutableState.update { it.copy(message = UiText.res(R.string.original_source_unavailable)) }
            } finally {
                if (binding == originals.currentOriginalBinding()) {
                    mutableState.update { it.copy(busy = false) }
                    if (state.value.selectionDraft != null) readRetainedSelection()
                }
            }
        }
    }

    fun confirmImageSelection(confirmed: Boolean) {
        mutableState.update { it.copy(selectionConfirmed = confirmed && it.selectionDisplayed && it.localIntentBound) }
    }
}
