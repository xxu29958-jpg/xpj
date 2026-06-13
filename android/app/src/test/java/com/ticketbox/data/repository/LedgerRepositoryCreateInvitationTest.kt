package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.InvitationCreateResponseDto
import com.ticketbox.data.remote.dto.InvitationSummaryDto
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import kotlinx.coroutines.test.runTest

/**
 * 轴7 发邀请:[LedgerRepository.createFamilyInvitation] 契约——角色白名单
 * (member/viewer,owner 走显式 owner-transfer 不走邀请)、ledger 路径与请求体透传、
 * 一次性明文 token 的 mapper 映射、API 失败折叠为 Result.failure。
 * 复用 [LedgerRepositoryTestFixtures] 的 StubApi / fake stores。
 */
class LedgerRepositoryCreateInvitationTest {

    /** 绑定态 fixture:api() 前置要求 serverUrl + token 双非空,activeLedger 供默认参数。 */
    private fun boundStore(): LedgerFakeSettingsStore =
        LedgerFakeSettingsStore().apply {
            saveServerUrl("https://family.example.com")
            saveActiveLedger("L_family", "家庭账本")
        }

    private fun repoWith(api: StubApi, store: LedgerFakeSettingsStore): LedgerRepository =
        LedgerRepository(
            apiClient = LedgerStubApiFactory(api),
            settingsStore = store,
            tokenStore = LedgerFakeTokenStore().apply { saveToken("session-token") },
            expenseDao = LedgerFakeDao(),
        )

    private fun createdResponse(role: String) = InvitationCreateResponseDto(
        inviteToken = "inv_PLAINTEXT_ONCE",
        invitation = InvitationSummaryDto(
            publicId = "I_1",
            ledgerId = "L_family",
            role = role,
            expiresAt = "2026-06-20T00:00:00+00:00",
        ),
    )

    @Test
    fun createsMemberInvitationAgainstActiveLedgerAndMapsPlaintextToken() = runTest {
        val api = StubApi(createInvitationResult = createdResponse(role = "member"))
        val store = boundStore()
        val created = repoWith(api, store)
            .createFamilyInvitation(role = "member")
            .getOrThrow()
        assertEquals("inv_PLAINTEXT_ONCE", created.inviteToken)
        assertEquals("member", created.role)
        assertEquals("2026-06-20T00:00:00+00:00", created.expiresAt)
        assertEquals(listOf("L_family"), api.createInvitationTargets)
        assertEquals("member", api.createInvitationRequests.single().role)
        // note / ttl_days 走后端默认:请求体不带 note、ttl 用 DTO 默认 7。
        assertEquals(null, api.createInvitationRequests.single().note)
        assertEquals(7, api.createInvitationRequests.single().ttlDays)
    }

    @Test
    fun trimsRoleAndAcceptsViewer() = runTest {
        val api = StubApi(createInvitationResult = createdResponse(role = "viewer"))
        val store = boundStore()
        val created = repoWith(api, store)
            .createFamilyInvitation(role = " viewer ")
            .getOrThrow()
        assertEquals("viewer", created.role)
        assertEquals("viewer", api.createInvitationRequests.single().role)
    }

    @Test
    fun rejectsOwnerRoleBeforeAnyApiCall() = runTest {
        // owner 经显式 owner-transfer,不走邀请——白名单在 repository 层先拒,请求不出门。
        val api = StubApi()
        val store = boundStore()
        val result = repoWith(api, store).createFamilyInvitation(role = "owner")
        assertTrue(result.isFailure)
        assertTrue(api.createInvitationRequests.isEmpty())
    }

    @Test
    fun apiFailureFoldsIntoResultFailure() = runTest {
        val api = StubApi(createInvitationError = RuntimeException("boom"))
        val store = boundStore()
        val result = repoWith(api, store).createFamilyInvitation(role = "member")
        assertTrue(result.isFailure)
    }
}
