package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.PortableExportActions
import com.ticketbox.data.repository.PortableExportSelection
import com.ticketbox.domain.model.LedgerSummary
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import java.io.OutputStream
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

enum class PortableExportStage { Idle, ChoosingLocation, Downloading }

data class PortableExportUiState(
    val binding: LogicalSessionBinding? = null,
    val loading: Boolean = false,
    val ledgers: List<LedgerSummary> = emptyList(),
    val selectedLedgerId: String? = null,
    val stage: PortableExportStage = PortableExportStage.Idle,
    val bytesWritten: Long = 0,
    val message: UiText? = null,
    val tone: MessageTone = MessageTone.Info,
)

/** Only the new document chosen for this request can be discarded after failure. */
interface PortableExportDestination {
    fun open(): OutputStream
    fun discard(): Boolean
}

class PortableExportViewModel(private val exports: PortableExportActions) : ViewModel() {
    private val mutable = MutableStateFlow(PortableExportUiState())
    val state = mutable.asStateFlow()
    private var read: Job? = null
    private var saving: Job? = null
    private var pending: PortableExportSelection? = null

    init {
        viewModelScope.launch {
            exports.observeBinding().collect { binding ->
                read?.cancel()
                saving?.cancel()
                pending = null
                mutable.value = PortableExportUiState(binding = binding)
                refresh()
            }
        }
    }

    fun refresh() {
        val current = mutable.value
        if (current.stage != PortableExportStage.Idle) return
        val binding = current.binding ?: return
        read?.cancel()
        mutable.update { it.copy(loading = true, message = null) }
        read = viewModelScope.launch {
            val result = exports.ledgers(binding)
            if (exports.currentBinding() != binding) return@launch
            result.fold(onSuccess = { ledgers ->
                mutable.update { it.copy(loading = false, ledgers = ledgers,
                    selectedLedgerId = it.selectedLedgerId?.takeIf { id -> ledgers.any { row -> row.ledgerId == id } }
                        ?: ledgers.firstOrNull()?.ledgerId) }
            }, onFailure = { error ->
                mutable.update { it.copy(loading = false, ledgers = emptyList(), selectedLedgerId = null,
                    message = error.toUiText(), tone = MessageTone.Danger) }
            })
        }
    }

    fun select(ledgerId: String) {
        if (mutable.value.stage == PortableExportStage.Idle && mutable.value.ledgers.any { it.ledgerId == ledgerId }) {
            mutable.update { it.copy(selectedLedgerId = ledgerId, message = null) }
        }
    }

    fun chooseLocation(): Boolean {
        val current = mutable.value
        val binding = current.binding ?: return false
        val selected = current.selectedLedgerId ?: return false
        if (current.loading || current.stage != PortableExportStage.Idle || exports.currentBinding() != binding) return false
        pending = PortableExportSelection(binding, selected)
        mutable.update { it.copy(stage = PortableExportStage.ChoosingLocation, bytesWritten = 0, message = null) }
        return true
    }

    fun save(destination: PortableExportDestination?) {
        val request = pending
        pending = null
        if (destination == null) {
            cancel()
            return
        }
        saving = viewModelScope.launch {
            if (request == null || request.binding != exports.currentBinding()) {
                finish(destination, null, cancelled = true, binding = mutable.value.binding)
                return@launch
            }
            mutable.update { it.copy(stage = PortableExportStage.Downloading) }
            var result: Result<Long>? = null
            try {
                result = exports.download(request, destination::open) { count ->
                    mutable.update { if (it.binding == request.binding) it.copy(bytesWritten = count) else it }
                }
            } finally {
                finish(destination, result, cancelled = result == null, binding = request.binding)
            }
        }
    }

    fun cancel() {
        pending = null
        if (saving?.isActive == true) saving?.cancel()
        else mutable.update { it.copy(stage = PortableExportStage.Idle,
            message = UiText.res(R.string.portable_export_cancelled), tone = MessageTone.Info) }
    }

    private suspend fun finish(destination: PortableExportDestination, result: Result<Long>?,
        cancelled: Boolean, binding: LogicalSessionBinding?) = withContext(NonCancellable) {
        val complete = result?.isSuccess == true
        val discarded = complete || withContext(Dispatchers.IO) {
            try { destination.discard() } catch (_: Exception) { false }
        }
        if (mutable.value.binding != binding) return@withContext
        val message = when {
            !discarded -> UiText.res(R.string.portable_export_partial)
            complete -> UiText.res(R.string.portable_export_saved)
            cancelled -> UiText.res(R.string.portable_export_cancelled)
            else -> result?.exceptionOrNull()?.toUiText() ?: UiText.res(R.string.portable_export_failed)
        }
        mutable.update { it.copy(stage = PortableExportStage.Idle, message = message,
            tone = if (complete) MessageTone.Success else if (cancelled && discarded) MessageTone.Info else MessageTone.Danger) }
    }
}
