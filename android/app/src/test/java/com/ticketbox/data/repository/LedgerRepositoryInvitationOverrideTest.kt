package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.InvitationAcceptResponseDto
import com.ticketbox.data.remote.dto.InvitationPreviewResponseDto
import com.ticketbox.data.remote.dto.LedgerDto
import com.ticketbox.data.remote.dto.LedgerListResponseDto
import kotlinx.coroutines.test.runTest
import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * serverUrlOverride(cold-start join)contract tests — split from
 * [LedgerRepositoryInvitationTest] to keep that class within the detekt
 * TooManyFunctions gate; same fixtures, override-specific theme.
 */
class LedgerRepositoryInvitationOverrideTest {

    @Test
    fun acceptInvitationWithServerUrlOverrideJoinsFromFullyUnboundDevice() = runTest {
        // Cold-start onboarding: nothing persisted at all — no server URL,
        // no token, no identity. The override must (a) be normalized through
        // the bind-screen URL rules, (b) go out unauthenticated, and (c) on
        // success persist URL + token + identity and mark the device
        // unlocked, exactly like pairing-code binding.
        val newToken = "session-token-joined"
        val api = StubApi(
            LedgerStubApiState(
                acceptResult = InvitationAcceptResponseDto(
                    sessionToken = newToken,
                    serverId = TEST_SERVER_ID,
                    dataGeneration = TEST_DATA_GENERATION,
                    accountPublicId = TEST_ACCOUNT_PUBLIC_ID,
                    devicePublicId = TEST_DEVICE_PUBLIC_ID,
                    accountName = "新成员",
                    ledgerId = "L_family",
                    ledgerName = "家庭账本",
                    deviceName = "Pixel 9",
                    role = "member",
                ),
                listLedgersResult = LedgerListResponseDto(
                    ledgers = listOf(ledgerDto("L_family", "家庭账本", role = "member")),
                ),
            ),
        )
        val store = LedgerFakeSettingsStore()
        val tokenStore = LedgerFakeTokenStore()
        val apiFactory = LedgerStubApiFactory(api)
        val repo = testLedgerRepository(
            apiClient = apiFactory,
            settingsStore = store,
            tokenStore = tokenStore,
            expenseDao = LedgerFakeDao(),
        )

        val summary = repo.acceptInvitation(
            inviteToken = "inv_JOIN",
            accountName = "新成员",
            deviceName = "",
            serverUrlOverride = "https://join.example.com/",
        ).getOrThrow()

        assertEquals("L_family", summary.ledgerId)
        assertEquals("member", summary.role)
        // Trailing slash trimmed BEFORE the request was built.
        assertEquals("https://join.example.com", apiFactory.baseUrls.first())
        // Unbound accept attaches no token (the override host never sees a
        // stored credential).
        assertNull(apiFactory.tokenProviders.first().invoke())
        assertNotNull(api.acceptRequests.single().enrollmentAttemptId)
        assertNotNull(api.acceptRequests.single().enrollmentAttemptSecret)
        assertEquals("新成员", api.acceptRequests.single().accountName)
        assertEquals("测试 Android 设备", api.acceptRequests.single().deviceName)
        // Binding persisted in the sole session authority; ordinary settings stay non-authoritative.
        val session = requireNotNull(tokenStore.sessionStore.currentSession())
        assertEquals("https://join.example.com", session.serverUrl)
        assertEquals(newToken, tokenStore.getToken())
        assertEquals("L_family", session.identity.ledgerId)
        assertEquals("新成员", session.identity.accountName)
        assertEquals("member", session.identity.role)
        assertNull(tokenStore.sessionStore.pendingDeviceEnrollment())
        assertNull(store.serverUrl())
        assertTrue(store.unlockedMarked)
    }

    @Test
    fun acceptInvitationWithoutOverrideStillRequiresBoundServer() = runTest {
        // No override + nothing persisted = the historic error, and the
        // request never leaves the device.
        val api = StubApi()
        val store = LedgerFakeSettingsStore()
        val tokenStore = LedgerFakeTokenStore()
        val repo = testLedgerRepository(
            apiClient = LedgerStubApiFactory(api),
            settingsStore = store,
            tokenStore = tokenStore,
            expenseDao = LedgerFakeDao(),
        )

        val failure = repo.acceptInvitation(
            inviteToken = "inv_NOBIND",
            accountName = "新成员",
            deviceName = "Pixel 9",
        ).exceptionOrNull()

        assertNotNull(failure)
        assertTrue(failure.message!!.contains("not bound"))
        assertTrue(api.acceptRequests.isEmpty())
        assertNull(store.serverUrl())
        assertNull(tokenStore.getToken())
    }

    @Test
    fun acceptInvitationWithOverrideCannotReplaceActiveSession() = runTest {
        val api = StubApi()
        val store = LedgerFakeSettingsStore().apply { saveServerUrl("https://old.example.com") }
        val tokenStore = LedgerFakeTokenStore().apply { saveToken("old-token") }
        val apiFactory = LedgerStubApiFactory(api)
        val repo = testLedgerRepository(
            apiClient = apiFactory,
            settingsStore = store,
            tokenStore = tokenStore,
            expenseDao = LedgerFakeDao(),
        )

        val failure = repo.acceptInvitation(
            inviteToken = "inv_SWITCH",
            accountName = "新成员",
            deviceName = "Pixel 9",
            serverUrlOverride = "https://new.example.com",
        ).exceptionOrNull()

        assertNotNull(failure)
        assertTrue(failure.message!!.contains("不能通过邀请覆盖"))
        assertTrue(api.acceptRequests.isEmpty())
        assertTrue(apiFactory.baseUrls.isEmpty())
        assertEquals("https://api.example.com", tokenStore.sessionStore.currentSession()?.serverUrl)
        assertEquals("old-token", tokenStore.getToken())
    }

    @Test
    fun invitationResponseLossReusesEnrollmentAfterRepositoryRecreation() = runTest {
        val response = InvitationAcceptResponseDto(
            sessionToken = "stable-session-token",
            serverId = TEST_SERVER_ID,
            dataGeneration = TEST_DATA_GENERATION,
            accountPublicId = TEST_ACCOUNT_PUBLIC_ID,
            devicePublicId = TEST_DEVICE_PUBLIC_ID,
            accountName = "新成员",
            ledgerId = "L_family",
            ledgerName = "家庭账本",
            deviceName = "Pixel 9",
            role = "member",
        )
        var calls = 0
        val api = StubApi(
            LedgerStubApiState(
                acceptHandler = { request ->
                    calls += 1
                    if (calls == 1) throw IOException("response lost after commit")
                    response.copy(enrollmentAttemptId = request.enrollmentAttemptId)
                },
                listLedgersResult = LedgerListResponseDto(
                    ledgers = listOf(ledgerDto("L_family", "家庭账本", role = "member")),
                ),
            ),
        )
        val store = LedgerFakeSettingsStore()
        val tokenStore = LedgerFakeTokenStore()
        val apiFactory = LedgerStubApiFactory(api)
        val firstRepository = testLedgerRepository(apiFactory, store, tokenStore, LedgerFakeDao())

        assertTrue(
            firstRepository.acceptInvitation(
                "inv_RECOVERABLE",
                "新成员",
                "Pixel 9",
                "https://join.example.com",
            ).isFailure,
        )
        val pending = requireNotNull(tokenStore.sessionStore.pendingDeviceEnrollment())
        assertNull(tokenStore.sessionStore.currentSession())

        val reconstructed = testLedgerRepository(apiFactory, store, tokenStore, LedgerFakeDao())
        reconstructed.acceptInvitation(
            "inv_RECOVERABLE",
            "不会覆盖首次意图",
            "另一名称",
            "https://join.example.com",
        ).getOrThrow()

        assertEquals(2, api.acceptRequests.size)
        assertEquals(pending.attemptId, api.acceptRequests[0].enrollmentAttemptId)
        assertEquals(pending.attemptId, api.acceptRequests[1].enrollmentAttemptId)
        assertEquals(
            api.acceptRequests[0].enrollmentAttemptSecret,
            api.acceptRequests[1].enrollmentAttemptSecret,
        )
        assertEquals("新成员", api.acceptRequests[1].accountName)
        assertNull(tokenStore.sessionStore.pendingDeviceEnrollment())
        assertEquals("stable-session-token", tokenStore.getToken())
    }

    @Test
    fun previewInvitationWithServerUrlOverrideWorksUnboundAndPersistsNothing() = runTest {
        val api = StubApi(
            LedgerStubApiState(
                previewResult = InvitationPreviewResponseDto(
                    serverId = TEST_SERVER_ID,
                    dataGeneration = TEST_DATA_GENERATION,
                    ledgerId = "L_family",
                    ledgerName = "家庭账本",
                    role = "member",
                    expiresAt = "2026-07-01T00:00:00Z",
                ),
            ),
        )
        val store = LedgerFakeSettingsStore()
        val tokenStore = LedgerFakeTokenStore()
        val apiFactory = LedgerStubApiFactory(api)
        val repo = testLedgerRepository(
            apiClient = apiFactory,
            settingsStore = store,
            tokenStore = tokenStore,
            expenseDao = LedgerFakeDao(),
        )

        val preview = repo.previewInvitation(
            inviteToken = "inv_PREVIEW_UNBOUND",
            serverUrlOverride = "https://join.example.com",
        ).getOrThrow()

        assertEquals("L_family", preview.ledgerId)
        assertEquals("https://join.example.com", apiFactory.baseUrls.single())
        assertNull(apiFactory.tokenProviders.single().invoke())
        // Preview is read-only: still fully unbound afterwards.
        assertNull(store.serverUrl())
        assertNull(tokenStore.getToken())
        assertNull(store.activeLedgerId())
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
