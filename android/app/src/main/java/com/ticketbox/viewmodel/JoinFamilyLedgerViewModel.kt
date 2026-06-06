package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.domain.model.InvitationPreview
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * Settings → Join family ledger.
 *
 * Preview-then-accept flow. The plain invite token never leaves this VM /
 * the screen state; once accept succeeds we wipe ``inviteToken``. Trust
 * model identical to the pre-refactor screen body — only the layer changed.
 */
data class JoinFamilyLedgerUiState(
    val preview: InvitationPreview? = null,
    val previewing: Boolean = false,
    val submitting: Boolean = false,
    val error: UiText? = null,
    val success: UiText? = null,
)

class JoinFamilyLedgerViewModel(
    private val repository: LedgerRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(JoinFamilyLedgerUiState())
    val uiState: StateFlow<JoinFamilyLedgerUiState> = _uiState.asStateFlow()

    val currentAccountName: UiText
        get() = repository.currentAccountName().displayOr(R.string.join_family_ledger_binding_unbound)
    val currentLedgerName: UiText
        get() = repository.currentLedgerName().displayOr(R.string.join_family_ledger_binding_unbound)
    val currentLedgerRole: String?
        get() = repository.currentLedgerRole()

    fun onTokenChanged() {
        _uiState.update { it.copy(preview = null, success = null) }
    }

    fun previewInvitation(inviteToken: String) {
        if (_uiState.value.previewing || _uiState.value.submitting) return
        viewModelScope.launch {
            _uiState.update { it.copy(previewing = true, error = null, success = null) }
            repository.previewInvitation(inviteToken)
                .onSuccess { preview ->
                    _uiState.update { it.copy(previewing = false, preview = preview) }
                }
                .onFailure { err ->
                    _uiState.update {
                        it.copy(
                            previewing = false,
                            preview = null,
                            error = err.toUiText(R.string.join_family_ledger_message_preview_failed),
                        )
                    }
                }
        }
    }

    fun acceptInvitation(
        inviteToken: String,
        accountName: String,
        deviceName: String,
        onAccepted: () -> Unit,
        onConsumed: () -> Unit,
    ) {
        val acceptedPreview = _uiState.value.preview ?: return
        if (_uiState.value.submitting) return
        viewModelScope.launch {
            _uiState.update { it.copy(submitting = true, error = null, success = null) }
            repository.acceptInvitation(
                inviteToken = inviteToken,
                accountName = accountName,
                deviceName = deviceName,
            ).onSuccess { ledger ->
                _uiState.update {
                    it.copy(
                        submitting = false,
                        preview = null,
                        success = UiText.res(
                            R.string.join_family_ledger_message_accepted,
                            ledger.name,
                            ledger.role,
                        ),
                    )
                }
                onConsumed()
                onAccepted()
            }.onFailure { err ->
                _uiState.update {
                    it.copy(
                        submitting = false,
                        preview = acceptedPreview,
                        error = err.toUiText(R.string.join_family_ledger_message_accept_failed),
                    )
                }
            }
        }
    }
}

private fun String?.displayOr(@androidx.annotation.StringRes fallback: Int): UiText =
    this?.takeIf { it.isNotBlank() }?.let { UiText.raw(it) } ?: UiText.res(fallback)
