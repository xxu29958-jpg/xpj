package com.ticketbox.viewmodel

import com.ticketbox.data.remote.dto.LedgerAuditDto
import com.ticketbox.data.remote.dto.LedgerAuditListResponseDto
import com.ticketbox.data.remote.dto.LedgerMemberDto
import com.ticketbox.data.remote.dto.LedgerMemberListResponseDto
import com.ticketbox.data.repository.LedgerFakeDao
import com.ticketbox.data.repository.LedgerFakeSettingsStore
import com.ticketbox.data.repository.LedgerFakeTokenStore
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.data.repository.LedgerStubApiFactory
import com.ticketbox.data.repository.StubApi
import com.ticketbox.domain.model.LEDGER_ROLE_MEMBER
import com.ticketbox.domain.model.LEDGER_ROLE_OWNER
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

@OptIn(ExperimentalCoroutinesApi::class)
class FamilyMembersViewModelTest {

    private val ledger = "L_family"

    @Test
    fun auditRefreshFailureKeepsExistingAuditRows() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = StubApi(
                membersResult = LedgerMemberListResponseDto(listOf(memberDto())),
                auditResult = LedgerAuditListResponseDto(listOf(auditDto("audit-1"))),
            )
            val vm = harness(api)

            vm.refresh(activeLedgerId = ledger, currentRole = LEDGER_ROLE_OWNER)
            val loaded = vm.uiState.first { !it.loading && it.auditItems.isNotEmpty() }
            assertEquals(listOf("audit-1"), loaded.auditItems.map { it.publicId })

            api.auditError = RuntimeException("offline")
            vm.refresh(activeLedgerId = ledger, currentRole = LEDGER_ROLE_OWNER)
            val failed = vm.uiState.first { !it.loading && it.message != null }

            assertEquals(listOf("audit-1"), failed.auditItems.map { it.publicId })
            assertFalse(failed.auditLoading)
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun nonOwnerRefreshClearsAuditRowsAndSkipsAuditFetch() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = StubApi(
                membersResult = LedgerMemberListResponseDto(listOf(memberDto())),
                auditResult = LedgerAuditListResponseDto(listOf(auditDto("audit-1"))),
            )
            val vm = harness(api)

            vm.refresh(activeLedgerId = ledger, currentRole = LEDGER_ROLE_OWNER)
            vm.uiState.first { !it.loading && it.auditItems.isNotEmpty() }

            vm.refresh(activeLedgerId = ledger, currentRole = LEDGER_ROLE_MEMBER)
            val memberView = vm.uiState.first { !it.loading && it.auditItems.isEmpty() && it.members.isNotEmpty() }

            assertEquals(listOf("L_family" to 20), api.auditRequests)
            assertEquals(listOf("owner"), memberView.members.map { it.role })
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

    private fun memberDto(): LedgerMemberDto = LedgerMemberDto(
        memberId = 1,
        accountId = 11,
        accountPublicId = "acc_owner",
        accountName = "Owner",
        role = LEDGER_ROLE_OWNER,
        createdAt = "2026-05-01T00:00:00Z",
        disabledAt = null,
        isSelf = true,
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
