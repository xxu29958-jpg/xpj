package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.InvitationAcceptResponseDto
import com.ticketbox.data.remote.dto.InvitationPreviewResponseDto
import com.ticketbox.data.remote.dto.LedgerDto
import com.ticketbox.data.remote.dto.LedgerListResponseDto
import kotlinx.coroutines.test.runTest
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response
import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class LedgerRepositoryInvitationTest {

    @Test
    fun acceptInvitationPersistsTokenIdentityAndWipesLocalAccountCache() = runTest {
        val newToken = "session-token-fresh"
        val api = StubApi(
            acceptResult = InvitationAcceptResponseDto(
                sessionToken = newToken,
                accountName = "二号",
                ledgerId = "L_family",
                ledgerName = "家庭账本",
                deviceName = "Pixel 8",
                role = "member",
            ),
            // refreshLedgers is called after accept; let it succeed with a tiny list.
            listLedgersResult = LedgerListResponseDto(
                ledgers = listOf(ledgerDto("L_family", "家庭账本", role = "member")),
            ),
        )
        val store = LedgerFakeSettingsStore().apply { saveServerUrl("https://api.example.com") }
        val tokenStore = LedgerFakeTokenStore().apply { saveToken("old-token") }
        val apiFactory = LedgerStubApiFactory(api)
        val dao = LedgerFakeDao().apply {
            // Invitation accept replaces the local account, so all old local
            // ledger caches must be discarded before the new identity is shown.
            insertEntity(ledgerEntity(id = 1, ledgerId = "L_family", serverId = 100))
            insertEntity(ledgerEntity(id = 2, ledgerId = "L_other", serverId = 200))
        }
        val repo = LedgerRepository(
            apiClient = apiFactory,
            settingsStore = store,
            tokenStore = tokenStore,
            expenseDao = dao,
        )

        val summary = repo.acceptInvitation(
            inviteToken = "  inv_PLAINTOKEN  ",
            accountName = "二号",
            deviceName = "Pixel 8",
        ).getOrThrow()

        assertEquals("L_family", summary.ledgerId)
        assertEquals("member", summary.role)
        // The plain token is trimmed before being sent to the server.
        assertEquals("inv_PLAINTOKEN", api.acceptRequests.single().inviteToken)
        assertEquals("android", api.acceptRequests.single().platform)
        // Bound-device invitation accept carries the replaced token so the server can revoke it.
        assertEquals("old-token", apiFactory.tokenProviders.first().invoke())
        // Token rotated; identity captured; active ledger switched.
        assertEquals(newToken, tokenStore.getToken())
        assertEquals("L_family", store.activeLedgerId())
        assertEquals("二号", store.capturedAccountName)
        assertEquals("Pixel 8", store.capturedDeviceName)
        assertEquals("member", store.capturedRole)
        assertFalse(store.capturedBoundAt.isNullOrBlank())
        // The account boundary was replaced; old ledger caches are gone.
        assertNull(dao.find(1))
        assertNull(dao.find(2))
    }

    @Test
    fun acceptInvitationSlowResponseDoesNotOverwriteBindingChangedDuringRequest() = runTest {
        val api = StubApi(
            acceptResult = InvitationAcceptResponseDto(
                sessionToken = "invite-token",
                accountName = "邀请账号",
                ledgerId = "L_invited",
                ledgerName = "邀请账本",
                deviceName = "Invite Pixel",
                role = "member",
            ),
        )
        val store = LedgerFakeSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveIdentity(
                accountName = "旧账号",
                ledgerId = "L_old",
                ledgerName = "旧账本",
                deviceName = "Old Pixel",
                role = "owner",
                boundAt = "2026-05-01T00:00:00Z",
            )
            saveAvailableLedgersJson(
                """
                [
                  {
                    "ledger_id": "L_new",
                    "name": "新账本",
                    "role": "owner",
                    "is_default": true,
                    "created_at": "2026-01-01T00:00:00Z",
                    "archived_at": null
                  }
                ]
                """.trimIndent(),
            )
        }
        val tokenStore = LedgerFakeTokenStore().apply { saveToken("old-token") }
        api.onAcceptInvitation = {
            tokenStore.saveToken("new-token")
            store.saveIdentity(
                accountName = "新账号",
                ledgerId = "L_new",
                ledgerName = "新账本",
                deviceName = "New Pixel",
                role = "owner",
                boundAt = "2026-05-01T00:05:00Z",
            )
        }
        val repo = LedgerRepository(
            apiClient = LedgerStubApiFactory(api),
            settingsStore = store,
            tokenStore = tokenStore,
            expenseDao = LedgerFakeDao(),
        )

        val failure = repo.acceptInvitation(
            inviteToken = "inv_SLOW",
            accountName = "邀请账号",
            deviceName = "Invite Pixel",
        ).exceptionOrNull()

        assertNotNull(failure)
        assertEquals("new-token", tokenStore.getToken())
        assertEquals("L_new", store.activeLedgerId())
        assertEquals("新账号", store.accountName())
        assertEquals(listOf("L_new"), repo.cachedLedgers().map { it.ledgerId })
    }

    @Test
    fun previewInvitationReturnsTargetWithoutReplacingExistingBinding() = runTest {
        val ledgerName = "家庭共同账本" + "很长".repeat(20)
        val api = StubApi(
            previewResult = InvitationPreviewResponseDto(
                ledgerId = "L_family",
                ledgerName = ledgerName,
                role = "viewer",
                expiresAt = "2026-05-20T00:00:00Z",
            ),
        )
        val store = LedgerFakeSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveIdentity(
                accountName = "旧账号",
                ledgerId = "L_old",
                ledgerName = "旧账本",
                deviceName = "Old Pixel",
                role = "owner",
                boundAt = "2026-05-01T00:00:00Z",
            )
        }
        val tokenStore = LedgerFakeTokenStore().apply { saveToken("old-token") }
        val apiFactory = LedgerStubApiFactory(api)
        val repo = LedgerRepository(
            apiClient = apiFactory,
            settingsStore = store,
            tokenStore = tokenStore,
            expenseDao = LedgerFakeDao(),
        )

        val preview = repo.previewInvitation("  inv_PREVIEW  ").getOrThrow()

        assertEquals("L_family", preview.ledgerId)
        assertEquals(ledgerName, preview.ledgerName)
        assertEquals("viewer", preview.role)
        assertEquals("2026-05-20T00:00:00Z", preview.expiresAt)
        assertEquals("inv_PREVIEW", api.previewRequests.single().inviteToken)
        // Invitation preview is a public endpoint; it must not attach the existing token.
        assertNull(apiFactory.tokenProviders.single().invoke())
        assertEquals("old-token", tokenStore.getToken())
        assertEquals("L_old", store.activeLedgerId())
        assertEquals("旧账号", store.accountName())
        assertEquals("owner", store.role())
    }

    @Test
    fun previewInvitationRejectsBlankTokenWithChineseMessage() = runTest {
        val repo = makeRepo()
        val failure = repo.previewInvitation("   ").exceptionOrNull()
        assertNotNull(failure)
        assertTrue(failure.message!!.contains("邀请明文"))
    }

    @Test
    fun previewInvitationNetworkFailurePreservesExistingBinding() = runTest {
        val api = StubApi(previewError = IOException("timeout"))
        val store = LedgerFakeSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveIdentity(
                accountName = "旧账号",
                ledgerId = "L_old",
                ledgerName = "旧账本",
                deviceName = "Old Pixel",
                role = "owner",
                boundAt = "2026-05-01T00:00:00Z",
            )
        }
        val tokenStore = LedgerFakeTokenStore().apply { saveToken("old-token") }
        val repo = LedgerRepository(
            apiClient = LedgerStubApiFactory(api),
            settingsStore = store,
            tokenStore = tokenStore,
            expenseDao = LedgerFakeDao(),
        )

        val failure = repo.previewInvitation("inv_TIMEOUT").exceptionOrNull()

        assertNotNull(failure)
        assertEquals("网络连接失败，请检查电脑端服务。", failure.message)
        assertEquals("old-token", tokenStore.getToken())
        assertEquals("L_old", store.activeLedgerId())
        assertEquals("旧账号", store.accountName())
    }

    @Test
    fun acceptInvitationRejectsBlankTokenWithChineseMessage() = runTest {
        val repo = makeRepo()
        val failure = repo.acceptInvitation(
            inviteToken = "   ",
            accountName = "二号",
            deviceName = "Pixel",
        ).exceptionOrNull()
        assertNotNull(failure)
        assertTrue(failure.message!!.contains("邀请明文"))
    }

    @Test
    fun acceptInvitationServerErrorPreservesOldTokenAndBinding() = runTest {
        val errorJson = "{\"error\":\"invalid_invite_token\",\"message\":\"邀请已过期或不存在\"}"
        val api = StubApi(
            acceptError = HttpException(
                Response.error<Any>(400, errorJson.toResponseBody("application/json".toMediaType())),
            ),
        )
        val store = LedgerFakeSettingsStore().apply { saveServerUrl("https://api.example.com") }
        val tokenStore = LedgerFakeTokenStore().apply { saveToken("old-token") }
        val repo = LedgerRepository(
            apiClient = LedgerStubApiFactory(api),
            settingsStore = store,
            tokenStore = tokenStore,
            expenseDao = LedgerFakeDao(),
        )

        val failure = repo.acceptInvitation(
            inviteToken = "inv_BAD",
            accountName = "二号",
            deviceName = "Pixel",
        ).exceptionOrNull()
        assertNotNull(failure)
        // Old token must NOT be overwritten on failure; identity not touched.
        assertEquals("old-token", tokenStore.getToken())
        assertNull(store.activeLedgerId())
        assertNull(store.capturedAccountName)
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
