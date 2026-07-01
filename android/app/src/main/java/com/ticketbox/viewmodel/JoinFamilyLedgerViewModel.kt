package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.domain.model.InvitationPreview
import com.ticketbox.domain.model.LEDGER_ROLE_MEMBER
import com.ticketbox.domain.model.LEDGER_ROLE_OWNER
import com.ticketbox.domain.model.LEDGER_ROLE_VIEWER
import com.ticketbox.domain.model.LedgerSummary
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * Settings → Join family ledger / cold-start「我有家庭邀请」entry.
 *
 * Preview-then-accept flow. The plain invite token never leaves this VM /
 * the screen state; once accept succeeds we wipe ``inviteToken``. Trust
 * model identical to the pre-refactor screen body — only the layer changed.
 *
 * Unbound-entry mode: [previewInvitation] may carry a ``serverUrlOverride``
 * (the URL collected on the cold-start screen). The override is **pinned to
 * the preview** — accept always reuses the URL that produced the preview the
 * user is looking at, and any URL edit ([onServerUrlChanged]) drops the
 * preview so the pair can never diverge.
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

    /** Server URL that produced the current [JoinFamilyLedgerUiState.preview];
     *  null in the bound (settings) flow. Only meaningful while preview != null. */
    private var previewedServerUrlOverride: String? = null

    val currentAccountName: UiText
        get() = repository.currentAccountName().displayOr(R.string.join_family_ledger_binding_unbound)
    val currentLedgerName: UiText
        get() = repository.currentLedgerName().displayOr(R.string.join_family_ledger_binding_unbound)
    val currentLedgerRole: String?
        get() = repository.currentLedgerRole()

    fun onTokenChanged() {
        _uiState.update { it.copy(preview = null, success = null) }
    }

    /** A server-URL edit invalidates the preview (it belongs to the old URL). */
    fun onServerUrlChanged() {
        _uiState.update { it.copy(preview = null, success = null) }
    }

    /** Back to a fresh state. The unbound entry calls this when the flow is
     *  (re-)entered, so an activity-retained instance can't leak a previous
     *  join's success/error into a brand-new attempt. */
    fun reset() {
        previewedServerUrlOverride = null
        _uiState.value = JoinFamilyLedgerUiState()
    }

    fun previewInvitation(inviteToken: String, serverUrlOverride: String? = null) {
        if (_uiState.value.previewing || _uiState.value.submitting) return
        viewModelScope.launch {
            _uiState.update { it.copy(previewing = true, error = null, success = null) }
            repository.previewInvitation(inviteToken, serverUrlOverride)
                .onSuccess { preview ->
                    previewedServerUrlOverride = serverUrlOverride
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
                serverUrlOverride = previewedServerUrlOverride,
            ).onSuccess { ledger ->
                _uiState.update {
                    it.copy(
                        submitting = false,
                        preview = null,
                        success = acceptedMessage(ledger),
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

private fun acceptedMessage(ledger: LedgerSummary): UiText {
    val name = ledger.name
    return when (ledger.role.trim()) {
        LEDGER_ROLE_OWNER -> UiText.res(R.string.join_family_ledger_message_accepted_owner, name)
        LEDGER_ROLE_MEMBER -> UiText.res(R.string.join_family_ledger_message_accepted_member, name)
        LEDGER_ROLE_VIEWER -> UiText.res(R.string.join_family_ledger_message_accepted_viewer, name)
        else -> UiText.res(R.string.join_family_ledger_message_accepted_unknown, name, ledger.role)
    }
}
