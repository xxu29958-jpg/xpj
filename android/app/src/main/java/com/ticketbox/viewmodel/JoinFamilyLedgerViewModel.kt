package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.domain.model.InvitationPreview
import com.ticketbox.domain.model.InvitationSessionTarget
import com.ticketbox.domain.model.LEDGER_ROLE_MEMBER
import com.ticketbox.domain.model.LEDGER_ROLE_OWNER
import com.ticketbox.domain.model.LEDGER_ROLE_VIEWER
import com.ticketbox.domain.model.LedgerSummary
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.navigation.FamilyInvitationLink
import com.ticketbox.ui.navigation.parseFamilyInvitationLink
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

/** All editable invitation fields and their preview live together in this activity-retained owner. */
data class JoinFamilyLedgerUiState(
    val invitationInput: String = "",
    val accountName: String = "",
    val serverUrl: String = "",
    val sourceHost: String? = null,
    val preview: InvitationPreview? = null,
    val target: InvitationSessionTarget? = null,
    val previewing: Boolean = false,
    val submitting: Boolean = false,
    val error: UiText? = null,
    val success: UiText? = null,
) {
    val accountNameRequired: Boolean
        get() = target == InvitationSessionTarget.Unbound

    val canAccept: Boolean
        get() = preview != null && target != InvitationSessionTarget.ForeignServer

    val canContinueInBrowser: Boolean
        get() = preview != null && target == InvitationSessionTarget.ForeignServer
}

class JoinFamilyLedgerViewModel(
    private val repository: LedgerRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(JoinFamilyLedgerUiState())
    val uiState: StateFlow<JoinFamilyLedgerUiState> = _uiState.asStateFlow()

    private var acceptedInviteToken: String? = null
    private var previewedServerUrlOverride: String? = null
    private var browserContinuationUrl: String? = null
    private var previewJob: Job? = null
    private var previewAttempt: Long = 0
    private var pendingSharedText: String? = null

    val currentAccountName: UiText
        get() = repository.currentAccountName().displayOr(R.string.join_family_ledger_binding_unbound)
    val currentLedgerName: UiText
        get() = repository.currentLedgerName().displayOr(R.string.join_family_ledger_binding_unbound)
    val currentLedgerRole: String?
        get() = repository.currentLedgerRole()

    fun reset(defaultServerUrl: String = "") {
        invalidatePreviewRequest()
        clearSensitiveInput()
        _uiState.value = JoinFamilyLedgerUiState(serverUrl = defaultServerUrl)
    }

    fun discardInvitation() = reset(_uiState.value.serverUrl)

    /** Manual paste. A complete Ticketbox link is consumed immediately and previewed. */
    fun onInvitationInputChanged(value: String) {
        val link = parseFamilyInvitationLink(value)
        if (link != null) {
            consumeInvitationLink(link)
            return
        }
        invalidatePreviewRequest()
        clearPreviewOwnership()
        acceptedInviteToken = null
        _uiState.update {
            it.copy(
                invitationInput = value,
                sourceHost = null,
                preview = null,
                target = null,
                previewing = false,
                error = null,
                success = null,
            )
        }
    }

    fun onServerUrlChanged(value: String) {
        invalidatePreviewRequest()
        clearPreviewOwnership()
        _uiState.update {
            it.copy(
                serverUrl = value,
                preview = null,
                target = null,
                previewing = false,
                error = null,
                success = null,
            )
        }
    }

    fun onAccountNameChanged(value: String) {
        _uiState.update { it.copy(accountName = value.take(NAME_MAX), error = null, success = null) }
    }

    /** Invalid shared text still lands here, producing an explicit failure instead of silently opening home. */
    fun consumeSharedInvitation(sharedText: String) {
        if (_uiState.value.submitting) {
            pendingSharedText = sharedText
            return
        }
        val link = parseFamilyInvitationLink(sharedText)
        if (link == null) {
            reset(_uiState.value.serverUrl)
            _uiState.update { it.copy(error = UiText.res(R.string.join_family_ledger_invalid_shared_text)) }
            return
        }
        consumeInvitationLink(link)
    }

    fun previewCurrentInput() {
        if (_uiState.value.previewing || _uiState.value.submitting) return
        if (_uiState.value.sourceHost != null && acceptedInviteToken != null) {
            previewAcceptedToken()
            return
        }
        val input = _uiState.value.invitationInput.trim()
        val link = parseFamilyInvitationLink(input)
        if (link != null) {
            consumeInvitationLink(link)
            return
        }
        acceptedInviteToken = input
        previewedServerUrlOverride = if (repository.hasBoundSession()) null else _uiState.value.serverUrl
        browserContinuationUrl = null
        previewAcceptedToken()
    }

    fun acceptCurrentInvitation(onAccepted: () -> Unit, onConsumed: () -> Unit = {}) {
        acceptInvitationInternal(onAccepted, onConsumed)
    }

    fun continueInBrowser(open: (String) -> Unit): Boolean {
        val url = browserContinuationUrl ?: return false
        if (!_uiState.value.canContinueInBrowser) return false
        open(url)
        return true
    }

    private fun consumeInvitationLink(link: FamilyInvitationLink) {
        if (_uiState.value.submitting) return
        if (browserContinuationUrl == link.browserUrl &&
            (_uiState.value.previewing || _uiState.value.preview != null)
        ) {
            return
        }
        invalidatePreviewRequest()
        acceptedInviteToken = link.inviteToken
        previewedServerUrlOverride = link.serverUrl
        browserContinuationUrl = link.browserUrl
        _uiState.update {
            it.copy(
                invitationInput = "",
                serverUrl = link.serverUrl,
                sourceHost = link.hostLabel,
                preview = null,
                target = null,
                previewing = false,
                error = null,
                success = null,
            )
        }
        previewAcceptedToken()
    }

    private fun previewAcceptedToken() {
        if (_uiState.value.submitting) return
        invalidatePreviewRequest()
        val inviteToken = acceptedInviteToken.orEmpty()
        val serverOverride = previewedServerUrlOverride
        val attempt = previewAttempt
        previewJob = viewModelScope.launch {
            _uiState.update { it.copy(previewing = true, error = null, success = null) }
            repository.previewInvitation(inviteToken, serverOverride)
                .onSuccess { preview ->
                    if (attempt != previewAttempt) return@onSuccess
                    _uiState.update {
                        it.copy(
                            previewing = false,
                            preview = preview,
                            target = repository.invitationSessionTarget(preview),
                        )
                    }
                }
                .onFailure { err ->
                    if (attempt != previewAttempt) return@onFailure
                    _uiState.update {
                        it.copy(
                            previewing = false,
                            preview = null,
                            target = null,
                            error = err.toUiText(R.string.join_family_ledger_message_preview_failed),
                        )
                    }
                }
        }
    }

    private fun acceptInvitationInternal(
        onAccepted: () -> Unit,
        onConsumed: () -> Unit,
    ) {
        val acceptedPreview = _uiState.value.preview ?: return
        val acceptedTarget = _uiState.value.target ?: return
        if (!_uiState.value.canAccept || _uiState.value.submitting) return
        val inviteToken = acceptedInviteToken ?: return
        viewModelScope.launch {
            _uiState.update { it.copy(submitting = true, error = null, success = null) }
            repository.acceptInvitation(
                inviteToken = inviteToken,
                accountName = _uiState.value.accountName,
                deviceName = "",
                serverUrlOverride = if (acceptedTarget == InvitationSessionTarget.Unbound) {
                    previewedServerUrlOverride
                } else {
                    null
                },
            ).onSuccess { ledger ->
                val nextSharedText = pendingSharedText
                pendingSharedText = null
                clearSensitiveInput()
                _uiState.value = JoinFamilyLedgerUiState(success = acceptedMessage(ledger))
                onConsumed()
                onAccepted()
                nextSharedText?.let(::consumeSharedInvitation)
            }.onFailure { err ->
                _uiState.update {
                    it.copy(
                        submitting = false,
                        preview = acceptedPreview,
                        target = acceptedTarget,
                        error = err.toUiText(R.string.join_family_ledger_message_accept_failed),
                    )
                }
            }
        }
    }

    private fun clearPreviewOwnership() {
        previewedServerUrlOverride = null
        browserContinuationUrl = null
    }

    private fun clearSensitiveInput() {
        acceptedInviteToken = null
        pendingSharedText = null
        clearPreviewOwnership()
    }

    private fun invalidatePreviewRequest() {
        previewAttempt += 1
        previewJob?.cancel()
        previewJob = null
    }

    private companion object {
        const val NAME_MAX = 120
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
