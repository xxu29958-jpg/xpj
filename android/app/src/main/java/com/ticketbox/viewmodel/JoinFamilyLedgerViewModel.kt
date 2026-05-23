package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.domain.model.InvitationPreview
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
    val error: String? = null,
    val success: String? = null,
)

class JoinFamilyLedgerViewModel(
    private val repository: LedgerRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(JoinFamilyLedgerUiState())
    val uiState: StateFlow<JoinFamilyLedgerUiState> = _uiState.asStateFlow()

    val currentAccountName: String
        get() = repository.currentAccountName().displayOr("未绑定")
    val currentLedgerName: String
        get() = repository.currentLedgerName().displayOr("未绑定")
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
                            error = err.message ?: "预览邀请失败。",
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
                        success = "已加入“${ledger.name}”，当前角色：${ledger.role}",
                    )
                }
                onConsumed()
                onAccepted()
            }.onFailure { err ->
                _uiState.update {
                    it.copy(
                        submitting = false,
                        preview = acceptedPreview,
                        error = err.message ?: "接受邀请失败。",
                    )
                }
            }
        }
    }
}

private fun String?.displayOr(fallback: String): String =
    this?.takeIf { it.isNotBlank() } ?: fallback
