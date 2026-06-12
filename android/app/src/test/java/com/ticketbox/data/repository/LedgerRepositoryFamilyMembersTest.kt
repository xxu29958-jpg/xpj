package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.LedgerAuditDto
import com.ticketbox.data.remote.dto.LedgerAuditListResponseDto
import com.ticketbox.data.remote.dto.LedgerMemberDto
import com.ticketbox.data.remote.dto.LedgerMemberListResponseDto
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class LedgerRepositoryFamilyMembersTest {

    @Test
    fun refreshFamilyMembersMapsServerFieldsToDomain() = runTest {
        val api = StubApi(
            membersResult = LedgerMemberListResponseDto(
                members = listOf(
                    LedgerMemberDto(
                        memberId = 1,
                        accountId = 11,
                        accountPublicId = "acc_owner",
                        accountName = "阿方",
                        role = "owner",
                        createdAt = "2026-05-01T00:00:00Z",
                        disabledAt = null,
                        isSelf = true,
                    ),
                    LedgerMemberDto(
                        memberId = 2,
                        accountId = 22,
                        accountPublicId = "acc_viewer",
                        accountName = "",
                        role = "viewer",
                        createdAt = null,
                        disabledAt = "2026-05-02T00:00:00Z",
                        isSelf = false,
                    ),
                ),
            ),
        )
        val store = LedgerFakeSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveActiveLedger("L_family", "家庭账本")
        }
        val repo = LedgerRepository(
            apiClient = LedgerStubApiFactory(api),
            settingsStore = store,
            tokenStore = LedgerFakeTokenStore().apply { saveToken("t") },
            expenseDao = LedgerFakeDao(),
        )

        val members = repo.refreshFamilyMembers().getOrThrow()

        assertEquals("L_family", api.memberLedgerRequests.single())
        assertEquals(listOf("阿方", "未命名成员"), members.map { it.displayName })
        assertEquals(listOf("owner", "viewer"), members.map { it.role })
        // ADR-0029 拆账发起 enabler：account_id 必须从 DTO 透传到 domain（split-invite
        // 的 receiver_account_id 来源）；与 memberId 是两套 id，不能糊成同一个。
        assertEquals(listOf(11L, 22L), members.map { it.accountId })
        assertTrue(members.first().isSelf)
        assertTrue(members.last().isDisabled)
    }

    @Test
    fun refreshFamilyMembersPersistsSelfRoleDowngrade() = runTest {
        val api = StubApi(
            membersResult = LedgerMemberListResponseDto(
                members = listOf(
                    LedgerMemberDto(
                        memberId = 1,
                        accountId = 11,
                        accountPublicId = "acc_self",
                        accountName = "我",
                        role = "viewer",
                        createdAt = "2026-05-01T00:00:00Z",
                        disabledAt = null,
                        isSelf = true,
                    ),
                ),
            ),
        )
        val store = LedgerFakeSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveIdentity(
                accountName = "我",
                ledgerId = "L_family",
                ledgerName = "家庭账本",
                deviceName = "Pixel",
                role = "owner",
                boundAt = "2026-05-01T00:00:00Z",
            )
        }
        val repo = LedgerRepository(
            apiClient = LedgerStubApiFactory(api),
            settingsStore = store,
            tokenStore = LedgerFakeTokenStore().apply { saveToken("t") },
            expenseDao = LedgerFakeDao(),
        )

        val members = repo.refreshFamilyMembers().getOrThrow()

        assertEquals("viewer", members.single().role)
        assertEquals("viewer", store.role())
        assertEquals("L_family", store.activeLedgerId())
    }

    @Test
    fun refreshFamilyMembersSlowResponseDoesNotPersistRoleAfterLedgerSwitch() = runTest {
        val api = StubApi(
            membersResult = LedgerMemberListResponseDto(
                members = listOf(
                    LedgerMemberDto(
                        memberId = 1,
                        accountId = 11,
                        accountPublicId = "acc_self",
                        accountName = "我",
                        role = "viewer",
                        createdAt = "2026-05-01T00:00:00Z",
                        disabledAt = null,
                        isSelf = true,
                    ),
                ),
            ),
        )
        val store = LedgerFakeSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveIdentity(
                accountName = "我",
                ledgerId = "L_family",
                ledgerName = "家庭账本",
                deviceName = "Pixel",
                role = "owner",
                boundAt = "2026-05-01T00:00:00Z",
            )
        }
        api.onLedgerMembers = {
            store.saveIdentity(
                accountName = "我",
                ledgerId = "L_other",
                ledgerName = "另一个账本",
                deviceName = "Pixel",
                role = "owner",
                boundAt = "2026-05-01T00:05:00Z",
            )
        }
        val repo = LedgerRepository(
            apiClient = LedgerStubApiFactory(api),
            settingsStore = store,
            tokenStore = LedgerFakeTokenStore().apply { saveToken("t") },
            expenseDao = LedgerFakeDao(),
        )

        val members = repo.refreshFamilyMembers().getOrThrow()

        assertEquals("viewer", members.single().role)
        assertEquals("L_other", store.activeLedgerId())
        assertEquals("owner", store.role())
    }

    @Test
    fun refreshFamilyMembersRejectsMissingActiveLedger() = runTest {
        val repo = makeRepo()
        val failure = repo.refreshFamilyMembers(null).exceptionOrNull()
        assertNotNull(failure)
        assertTrue(failure.message!!.contains("当前账本"))
    }

    @Test
    fun refreshFamilyAuditMapsServerFieldsAndClampsLimit() = runTest {
        val api = StubApi(
            auditResult = LedgerAuditListResponseDto(
                items = listOf(
                    LedgerAuditDto(
                        publicId = "audit-1",
                        ledgerId = "L_family",
                        action = "member_role_changed",
                        actorAccountPublicId = "acc_owner",
                        actorAccountName = "阿方",
                        targetAccountPublicId = "acc_member",
                        targetAccountName = "",
                        targetMemberId = 2,
                        invitationPublicId = null,
                        previousRole = "member",
                        newRole = "viewer",
                        result = "success",
                        detail = "hidden-detail",
                        createdAt = "2026-05-13T00:00:00Z",
                    ),
                ),
            ),
        )
        val store = LedgerFakeSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveActiveLedger("L_family", "家庭账本")
        }
        val repo = LedgerRepository(
            apiClient = LedgerStubApiFactory(api),
            settingsStore = store,
            tokenStore = LedgerFakeTokenStore().apply { saveToken("t") },
            expenseDao = LedgerFakeDao(),
        )

        val audit = repo.refreshFamilyAudit(limit = 500).getOrThrow()

        assertEquals(listOf("L_family" to 200), api.auditRequests)
        assertEquals("audit-1", audit.single().publicId)
        assertEquals("member_role_changed", audit.single().action)
        assertEquals("阿方", audit.single().actorName)
        assertNull(audit.single().targetName)
        assertEquals(2L, audit.single().targetMemberId)
        assertEquals("member", audit.single().previousRole)
        assertEquals("viewer", audit.single().newRole)
        assertEquals("success", audit.single().result)
    }

    @Test
    fun refreshFamilyAuditRejectsMissingActiveLedger() = runTest {
        val repo = makeRepo()
        val failure = repo.refreshFamilyAudit(null).exceptionOrNull()
        assertNotNull(failure)
        assertTrue(failure.message!!.contains("当前账本"))
    }

    private fun makeRepo(): LedgerRepository {
        val store = LedgerFakeSettingsStore().apply { saveServerUrl("https://api.example.com") }
        val tokenStore = LedgerFakeTokenStore().apply { saveToken("t") }
        return LedgerRepository(
            apiClient = LedgerStubApiFactory(StubApi()),
            settingsStore = store,
            tokenStore = tokenStore,
            expenseDao = LedgerFakeDao(),
        )
    }
}
