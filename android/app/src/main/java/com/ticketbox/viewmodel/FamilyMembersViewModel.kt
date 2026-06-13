package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.domain.model.FamilyInvitationCreated
import com.ticketbox.domain.model.FamilyMember
import com.ticketbox.domain.model.LEDGER_ROLE_OWNER
import com.ticketbox.domain.model.LedgerAuditEntry
import com.ticketbox.domain.model.UiText
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
    val message: UiText? = null,
    /** 轴7 发邀请:生成请求在途(禁双击)。 */
    val inviteCreating: Boolean = false,
    /**
     * 最近一次生成的邀请(明文 token 只在创建响应出现一次,故由本状态持有直到用户
     * 收起/再次生成覆盖/离开屏幕)。非 null 时屏幕渲染结果卡(token+复制+有效期)。
     */
    val createdInvite: FamilyInvitationCreated? = null,
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
                        it.copy(message = err.toUiText(R.string.family_members_message_members_load_failed))
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
                                    err.toUiText(R.string.family_members_message_audit_load_failed)
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

    /**
     * 轴7 发邀请(owner-only:屏幕按 currentRole 隐藏入口,这里再以 [deviceIsOwner]
     * 双查,后端 403 兜底)。成功置 [FamilyMembersUiState.createdInvite] 渲染结果卡。
     */
    fun createInvitation(role: String, activeLedgerId: String?) {
        if (!deviceIsOwner()) return
        viewModelScope.launch {
            _uiState.update { it.copy(inviteCreating = true, message = null) }
            repository.createFamilyInvitation(role = role, ledgerId = activeLedgerId)
                .onSuccess { created ->
                    _uiState.update {
                        it.copy(inviteCreating = false, createdInvite = created)
                    }
                }
                .onFailure { err ->
                    _uiState.update {
                        it.copy(
                            inviteCreating = false,
                            message = err.toUiText(R.string.family_members_message_invite_failed),
                        )
                    }
                }
        }
    }

    /** 收起邀请结果卡(明文不再展示;服务端只存哈希,收起后不可再取回)。 */
    fun dismissCreatedInvite() {
        _uiState.update { it.copy(createdInvite = null) }
    }

    fun runAction(
        action: FamilyMemberAction,
        activeLedgerId: String?,
        currentRole: String?,
        onMembershipChanged: () -> Unit,
    ) {
        viewModelScope.launch {
            _uiState.update { it.copy(busyMemberId = action.member.memberId, message = null) }
            val result: Result<UiText> = when (action) {
                is FamilyMemberAction.ChangeRole -> repository.updateFamilyMemberRole(
                    memberId = action.member.memberId,
                    role = action.targetRole,
                    ledgerId = activeLedgerId,
                ).map {
                    UiText.res(
                        R.string.family_members_message_role_changed,
                        action.member.displayName,
                        ledgerRoleLabel(action.targetRole),
                    )
                }

                is FamilyMemberAction.Disable -> repository.disableFamilyMember(
                    memberId = action.member.memberId,
                    ledgerId = activeLedgerId,
                ).map { UiText.res(R.string.family_members_message_disabled, action.member.displayName) }

                is FamilyMemberAction.TransferOwner -> repository.transferOwner(
                    memberId = action.member.memberId,
                    ledgerId = activeLedgerId,
                ).map {
                    UiText.res(R.string.family_members_message_owner_transferred, action.member.displayName)
                }
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
                            message = err.toUiText(R.string.family_members_message_action_failed),
                        )
                    }
                }
        }
    }
}
