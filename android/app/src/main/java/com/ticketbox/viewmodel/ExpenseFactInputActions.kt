package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.StreamOffsetKind
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** User recovery and navigation for the same local original-input session. */
fun ExpenseFactViewModel.resumeFactInput(key: String) {
    when {
        key == "correction" -> openCorrectionSheet()
        key == "refund" -> openOffsetSheet(StreamOffsetKind.Refund)
        key == "reversal" -> openOffsetSheet(StreamOffsetKind.Reversal)
        key.startsWith("void:") -> factInputSession?.draft(key)?.voidTarget?.let(::openVoidOffsetSheet)
    }
}

fun ExpenseFactViewModel.discardFactInput(key: String) {
    val session = factInputSession ?: return
    if (factInputOperationBusy()) return
    _uiState.update { it.copy(factInputBusy = true) }
    viewModelScope.launch {
        session.discard(key).onSuccess {
            if (factInputSession !== session) return@onSuccess
            _uiState.update { state -> when {
                key == "correction" -> state.copy(correction = CorrectionFormState())
                key == state.offsetForm.inputKey() -> state.copy(offsetForm = OffsetFormState())
                key == "void:${state.voidOffsetForm.target?.publicId}" -> state.copy(voidOffsetForm = VoidOffsetFormState())
                else -> state
            } }
        }
        if (factInputSession === session) _uiState.update { it.copy(factInputBusy = false) }
    }
}

fun ExpenseFactViewModel.retryFactInputSave() {
    if (factInputOperationBusy()) return
    if (!_uiState.value.factInputsReady) { loadFactOriginalInputs(); return }
    val session = factInputSession ?: return
    session.retry()
}

internal fun ExpenseFactViewModel.factInputUnavailable(): Boolean {
    if (_uiState.value.factInputsReady && !_uiState.value.factInputBusy) return false
    _uiState.update { it.copy(message = UiText.res(R.string.expense_fact_input_load_failed), messageTone = MessageTone.Danger) }
    return true
}

internal fun ExpenseFactViewModel.factInputOperationBusy(): Boolean = _uiState.value.let {
    it.factInputBusy || it.correction.saving || it.offsetForm.saving || it.voidOffsetForm.saving
}

internal fun ExpenseFactViewModel.canEditFactInput(key: String): Boolean = _uiState.value.let {
    !it.readOnly && it.factInputsReady && !factInputOperationBusy() &&
        factInputSession?.original(key)?.binding == it.correctionAccess?.binding
}

/** Navigation waits only for local persistence; a disk failure leaves the working input visible. */
fun ExpenseFactViewModel.leaveFactPage(onExit: () -> Unit) {
    if (factInputOperationBusy()) return
    val session = factInputSession
    if (session == null) { onExit(); return }
    _uiState.update { it.copy(factInputBusy = true) }
    viewModelScope.launch {
        val result = session.flush()
        if (factInputSession !== session) return@launch
        _uiState.update { it.copy(factInputBusy = false,
            factInputError = result.exceptionOrNull()?.toUiText(R.string.expense_fact_input_save_failed)) }
        if (result.isSuccess) onExit()
    }
}

