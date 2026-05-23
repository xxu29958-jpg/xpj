package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.domain.model.FamilyMember
import com.ticketbox.domain.model.LEDGER_ROLE_OWNER
import com.ticketbox.domain.model.LedgerAuditEntry
import com.ticketbox.domain.model.ledgerRoleLabel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * Settings → Family members. Pulled out of FamilyMembersScreen to comply
 * with the Android layer rule (Screen → ViewModel → Repository → IO).
 *
 * UI-only state (``pendingAction`` confirm dialog visibility) stays in the
 * screen; everything that touches Repository or backend state lives here.
 */
data class FamilyMembersUiState(
    val members: List<FamilyMember> = emptyList(),
    val auditItems: List<LedgerAuditEntry> = emptyList(),
    val loading: Boolean = false,
    val auditLoading: Boolean = false,
    val busyMemberId: Long? = null,
    val message: String? = null,
)

sealed class FamilyMemberAction(open val member: FamilyMember) {
    data class ChangeRole(
        override val member: FamilyMember,
        val targetRole: String,
    ) : FamilyMemberAction(member)

    data class Disable(override val member: FamilyMember) : FamilyMemberAction(member)

    data class TransferOwner(override val member: FamilyMember) : FamilyMemberAction(member)
}

class FamilyMembersViewModel(
    private val repository: LedgerRepository,
) : ViewModel() {

    private val _uiState = MutableStateFlow(FamilyMembersUiState())
    val uiState: StateFlow<FamilyMembersUiState> = _uiState.asStateFlow()

    /** Returns true if the currently-bound device's session is OWNER on
     * the active ledger. The screen still checks ``currentRole`` (passed
     * in from the upper-level SettingsUiState) AND this, so a stale
     * Repository cache cannot widen permissions. */
    fun deviceIsOwner(): Boolean =
        repository.currentLedgerRole() == LEDGER_ROLE_OWNER

    fun refresh(activeLedgerId: String?, currentRole: String?, includeAudit: Boolean = true) {
        viewModelScope.launch {
            _uiState.update { it.copy(loading = true, message = null) }
            val memberResult = repository.refreshFamilyMembers(activeLedgerId)
            memberResult
                .onSuccess { fetched ->
                    _uiState.update { it.copy(members = fetched) }
                }
                .onFailure { err ->
                    _uiState.update {
                        it.copy(message = err.message ?: "成员列表暂时打不开。")
                    }
                }
            val shouldLoadAudit = includeAudit &&
                currentRole == LEDGER_ROLE_OWNER &&
                deviceIsOwner()
            if (shouldLoadAudit) {
                _uiState.update { it.copy(auditLoading = true) }
                repository.refreshFamilyAudit(activeLedgerId, limit = 20)
                    .onSuccess { audit ->
                        _uiState.update { it.copy(auditItems = audit) }
                    }
                    .onFailure { err ->
                        _uiState.update {
                            it.copy(
                                auditItems = emptyList(),
                                // Don't overwrite the member-fetch error message; only
                                // surface the audit error if the members fetch was OK.
                                message = if (memberResult.isSuccess) {
                                    err.message ?: "成员记录暂时打不开。"
                                } else {
                                    it.message
                                },
                            )
                        }
                    }
                _uiState.update { it.copy(auditLoading = false) }
            } else {
                _uiState.update { it.copy(auditItems = emptyList()) }
            }
            _uiState.update { it.copy(loading = false) }
        }
    }

    fun runAction(
        action: FamilyMemberAction,
        activeLedgerId: String?,
        currentRole: String?,
        onMembershipChanged: () -> Unit,
    ) {
        viewModelScope.launch {
            _uiState.update { it.copy(busyMemberId = action.member.memberId, message = null) }
            val result = when (action) {
                is FamilyMemberAction.ChangeRole -> repository.updateFamilyMemberRole(
                    memberId = action.member.memberId,
                    role = action.targetRole,
                    ledgerId = activeLedgerId,
                ).map { "已将${action.member.displayName}设为${ledgerRoleLabel(action.targetRole)}。" }

                is FamilyMemberAction.Disable -> repository.disableFamilyMember(
                    memberId = action.member.memberId,
                    ledgerId = activeLedgerId,
                ).map { "已停用${action.member.displayName}。" }

                is FamilyMemberAction.TransferOwner -> repository.transferOwner(
                    memberId = action.member.memberId,
                    ledgerId = activeLedgerId,
                ).map { "已将拥有者转让给${action.member.displayName}。" }
            }
            result
                .onSuccess { success ->
                    refresh(
                        activeLedgerId = activeLedgerId,
                        currentRole = currentRole,
                        includeAudit = action !is FamilyMemberAction.TransferOwner,
                    )
                    _uiState.update {
                        it.copy(busyMemberId = null, message = success)
                    }
                    onMembershipChanged()
                }
                .onFailure { err ->
                    _uiState.update {
                        it.copy(
                            busyMemberId = null,
                            message = err.message ?: "成员管理操作没有完成。",
                        )
                    }
                }
        }
    }
}
