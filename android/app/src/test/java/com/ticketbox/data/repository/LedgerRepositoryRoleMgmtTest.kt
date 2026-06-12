package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.LedgerDto
import com.ticketbox.data.remote.dto.LedgerListResponseDto
import com.ticketbox.data.remote.dto.LedgerMemberDto
import com.ticketbox.data.remote.dto.OwnerTransferResponseDto
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class LedgerRepositoryRoleMgmtTest {

    @Test
    fun updateFamilyMemberRolePostsTrimmedRoleAndMapsResponse() = runTest {
        val api = StubApi(
            roleUpdateResult = LedgerMemberDto(
                memberId = 2,
                accountId = 22,
                accountPublicId = "acc_member",
                accountName = "家人",
                role = "viewer",
                createdAt = "2026-05-01T00:00:00Z",
                disabledAt = null,
                isSelf = false,
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

        val updated = repo.updateFamilyMemberRole(2, " viewer ").getOrThrow()

        assertEquals("viewer", updated.role)
        assertEquals(listOf("L_family" to 2L), api.roleUpdateTargets)
        assertEquals("viewer", api.roleUpdateRequests.single().role)
    }

    @Test
    fun updateFamilyMemberRoleRejectsOwnerRoleLocally() = runTest {
        val repo = makeRepo()
        val failure = repo.updateFamilyMemberRole(2, "owner", ledgerId = "L_family").exceptionOrNull()

        assertNotNull(failure)
        assertTrue(failure.message!!.contains("成员角色只能是成员或只读"))
    }

    @Test
    fun disableFamilyMemberPostsTargetAndMapsResponse() = runTest {
        val api = StubApi(
            disableResult = LedgerMemberDto(
                memberId = 2,
                accountId = 22,
                accountPublicId = "acc_member",
                accountName = "家人",
                role = "member",
                createdAt = "2026-05-01T00:00:00Z",
                disabledAt = "2026-05-13T00:00:00Z",
                isSelf = false,
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

        val disabled = repo.disableFamilyMember(2).getOrThrow()

        assertTrue(disabled.isDisabled)
        assertEquals(listOf("L_family" to 2L), api.disableTargets)
    }

    @Test
    fun transferOwnerDemotesSelfRoleAndRefreshesLedgerCache() = runTest {
        val api = StubApi(
            transferResult = OwnerTransferResponseDto(
                ledgerId = "L_family",
                previousOwner = LedgerMemberDto(
                    memberId = 1,
                    accountId = 11,
                    accountPublicId = "acc_self",
                    accountName = "我",
                    role = "member",
                    createdAt = "2026-05-01T00:00:00Z",
                    disabledAt = null,
                    isSelf = true,
                ),
                newOwner = LedgerMemberDto(
                    memberId = 2,
                    accountId = 22,
                    accountPublicId = "acc_new",
                    accountName = "家人",
                    role = "owner",
                    createdAt = "2026-05-02T00:00:00Z",
                    disabledAt = null,
                    isSelf = false,
                ),
            ),
            listLedgersResult = LedgerListResponseDto(
                ledgers = listOf(ledgerDto("L_family", "家庭账本", role = "member")),
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

        val result = repo.transferOwner(2).getOrThrow()

        assertEquals("member", result.previousOwner.role)
        assertEquals("owner", result.newOwner.role)
        assertEquals("member", store.role())
        assertEquals(listOf("L_family" to 2L), api.transferTargets)
        assertEquals("member", repo.cachedLedgers().single().role)
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

    private fun ledgerDto(
        id: String,
        name: String,
        role: String = "owner",
        isDefault: Boolean = false,
    ) = LedgerDto(
        ledgerId = id,
        name = name,
        role = role,
        isDefault = isDefault,
        createdAt = "2026-01-01T00:00:00Z",
        archivedAt = null,
    )
}
