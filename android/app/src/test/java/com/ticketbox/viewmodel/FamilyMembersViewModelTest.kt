package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.remote.dto.LedgerAuditDto
import com.ticketbox.data.remote.dto.LedgerAuditListResponseDto
import com.ticketbox.data.remote.dto.LedgerDto
import com.ticketbox.data.remote.dto.LedgerListResponseDto
import com.ticketbox.data.remote.dto.LedgerMemberDto
import com.ticketbox.data.remote.dto.LedgerMemberListResponseDto
import com.ticketbox.data.remote.dto.OwnerTransferResponseDto
import com.ticketbox.data.repository.LedgerFakeDao
import com.ticketbox.data.repository.LedgerFakeSettingsStore
import com.ticketbox.data.repository.LedgerFakeTokenStore
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.data.repository.LedgerStubApiState
import com.ticketbox.data.repository.LedgerStubApiFactory
import com.ticketbox.data.repository.StubApi
import com.ticketbox.domain.model.LEDGER_ROLE_MEMBER
import com.ticketbox.domain.model.LEDGER_ROLE_OWNER
import com.ticketbox.domain.model.LEDGER_ROLE_VIEWER
import com.ticketbox.domain.model.FamilyMember
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class FamilyMembersViewModelTest {

    private val ledger = "L_family"

    @Test
    fun auditRefreshFailureKeepsExistingAuditRows() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = StubApi(LedgerStubApiState(
                membersResult = LedgerMemberListResponseDto(listOf(memberDto())),
                auditResult = LedgerAuditListResponseDto(listOf(auditDto("audit-1"))),
            ))
            val vm = harness(api)

            vm.refresh(activeLedgerId = ledger, currentRole = LEDGER_ROLE_OWNER)
            val loaded = vm.uiState.first { !it.loading && it.auditItems.isNotEmpty() }
            assertEquals(listOf("audit-1"), loaded.auditItems.map { it.publicId })

            api.auditError = RuntimeException("offline")
            vm.refresh(activeLedgerId = ledger, currentRole = LEDGER_ROLE_OWNER)
            val failed = vm.uiState.first { !it.loading && it.message != null }

            assertEquals(listOf("audit-1"), failed.auditItems.map { it.publicId })
            assertFalse(failed.auditLoading)
            assertEquals(MessageTone.Danger, failed.messageTone)
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun nonOwnerRefreshClearsAuditRowsAndSkipsAuditFetch() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = StubApi(LedgerStubApiState(
                membersResult = LedgerMemberListResponseDto(listOf(memberDto())),
                auditResult = LedgerAuditListResponseDto(listOf(auditDto("audit-1"))),
            ))
            val vm = harness(api)

            vm.refresh(activeLedgerId = ledger, currentRole = LEDGER_ROLE_OWNER)
            vm.uiState.first { !it.loading && it.auditItems.isNotEmpty() }

            vm.refresh(activeLedgerId = ledger, currentRole = LEDGER_ROLE_MEMBER)
            val memberView = vm.uiState.first { !it.loading && it.auditItems.isEmpty() && it.members.isNotEmpty() }

            assertEquals(listOf("L_family" to 20), api.auditRequests)
            assertEquals(listOf("owner"), memberView.members.map { it.role })
            assertEquals(MessageTone.Neutral, memberView.messageTone)
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun invitationFailureShowsDangerTone() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = StubApi(LedgerStubApiState(createInvitationError = RuntimeException("offline")))
            val vm = harness(api)

            vm.createInvitation(role = LEDGER_ROLE_MEMBER, activeLedgerId = ledger)
            val state = vm.uiState.first { !it.inviteCreating && it.message != null }

            assertNotNull(state.message)
            assertEquals(MessageTone.Danger, state.messageTone)
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun memberActionFailureShowsDangerTone() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = StubApi()
            val vm = harness(api)

            vm.runAction(
                action = FamilyMemberAction.Disable(targetMember()),
                activeLedgerId = ledger,
                currentRole = LEDGER_ROLE_OWNER,
                onMembershipChanged = {},
            )
            val state = vm.uiState.first { it.busyMemberId == null && it.message != null }

            assertNotNull(state.message)
            assertEquals(MessageTone.Danger, state.messageTone)
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun memberActionSuccessShowsSuccessToneAfterRefresh() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = StubApi(LedgerStubApiState(
                membersResult = LedgerMemberListResponseDto(
                    listOf(memberDto(), memberDto(id = 2, name = "Member", role = LEDGER_ROLE_VIEWER, isSelf = false)),
                ),
                auditResult = LedgerAuditListResponseDto(emptyList()),
                roleUpdateResult = memberDto(id = 2, name = "Member", role = LEDGER_ROLE_VIEWER, isSelf = false),
            ))
            val vm = harness(api)
            var changed = false

            vm.runAction(
                action = FamilyMemberAction.ChangeRole(targetMember(), LEDGER_ROLE_VIEWER),
                activeLedgerId = ledger,
                currentRole = LEDGER_ROLE_OWNER,
                onMembershipChanged = { changed = true },
            )
            val state = vm.uiState.first { it.busyMemberId == null && it.messageTone == MessageTone.Success }

            assertTrue(changed)
            assertEquals(ledger to 2L, api.roleUpdateTargets.single())
            assertEquals(UiText.res(R.string.family_members_message_role_changed_viewer, "Member"), state.message)
            assertEquals(MessageTone.Success, state.messageTone)
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun ownerTransferSuccessShowsSuccessToneWithoutAuditRefresh() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = StubApi(LedgerStubApiState(
                membersResult = LedgerMemberListResponseDto(
                    listOf(memberDto(role = LEDGER_ROLE_MEMBER), memberDto(id = 2, name = "Member", isSelf = false)),
                ),
                transferResult = OwnerTransferResponseDto(
                    ledgerId = ledger,
                    previousOwner = memberDto(role = LEDGER_ROLE_MEMBER),
                    newOwner = memberDto(id = 2, name = "Member", role = LEDGER_ROLE_OWNER, isSelf = false),
                ),
                listLedgersResult = LedgerListResponseDto(listOf(ledgerDto())),
            ))
            val vm = harness(api)

            vm.runAction(
                action = FamilyMemberAction.TransferOwner(targetMember()),
                activeLedgerId = ledger,
                currentRole = LEDGER_ROLE_OWNER,
                onMembershipChanged = {},
            )
            val state = vm.uiState.first { it.busyMemberId == null && it.messageTone == MessageTone.Success }

            assertEquals(ledger to 2L, api.transferTargets.single())
            assertTrue(api.auditRequests.isEmpty())
            assertEquals(UiText.res(R.string.family_members_message_owner_transferred, "Member"), state.message)
            assertEquals(MessageTone.Success, state.messageTone)
        } finally {
            Dispatchers.resetMain()
        }
    }

    private fun harness(api: StubApi, role: String = LEDGER_ROLE_OWNER): FamilyMembersViewModel {
        val store = LedgerFakeSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveActiveLedger(ledger, "Family")
            capturedRole = role
        }
        val repository = LedgerRepository(
            apiClient = LedgerStubApiFactory(api),
            settingsStore = store,
            tokenStore = LedgerFakeTokenStore().apply { saveToken("t") },
            expenseDao = LedgerFakeDao(),
        )
        return FamilyMembersViewModel(repository)
    }

    private fun memberDto(
        id: Long = 1,
        name: String = "Owner",
        role: String = LEDGER_ROLE_OWNER,
        isSelf: Boolean = true,
    ): LedgerMemberDto = LedgerMemberDto(
        memberId = id,
        accountId = 10 + id,
        accountPublicId = "acc_$id",
        accountName = name,
        role = role,
        createdAt = "2026-05-01T00:00:00Z",
        disabledAt = null,
        isSelf = isSelf,
    )

    private fun targetMember(): FamilyMember = FamilyMember(
        memberId = 2,
        accountId = 12,
        accountPublicId = "acc_2",
        displayName = "Member",
        role = LEDGER_ROLE_MEMBER,
        joinedAt = "2026-05-01T00:00:00Z",
        disabledAt = null,
        isSelf = false,
    )

    private fun ledgerDto(): LedgerDto = LedgerDto(
        ledgerId = ledger,
        name = "Family",
        role = LEDGER_ROLE_MEMBER,
        isDefault = false,
        createdAt = "2026-01-01T00:00:00Z",
        archivedAt = null,
    )

    private fun auditDto(publicId: String): LedgerAuditDto = LedgerAuditDto(
        publicId = publicId,
        ledgerId = ledger,
        action = "member_role_changed",
        actorAccountPublicId = "acc_owner",
        actorAccountName = "Owner",
        targetAccountPublicId = "acc_member",
        targetAccountName = "Member",
        targetMemberId = 2,
        invitationPublicId = null,
        previousRole = LEDGER_ROLE_MEMBER,
        newRole = LEDGER_ROLE_OWNER,
        result = "success",
        detail = null,
        createdAt = "2026-05-13T00:00:00Z",
    )
}
