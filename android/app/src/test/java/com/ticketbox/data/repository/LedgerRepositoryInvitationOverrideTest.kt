package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.InvitationAcceptResponseDto
import com.ticketbox.data.remote.dto.InvitationPreviewResponseDto
import com.ticketbox.data.remote.dto.LedgerDto
import com.ticketbox.data.remote.dto.LedgerListResponseDto
import kotlinx.coroutines.test.runTest
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
            acceptResult = InvitationAcceptResponseDto(
                sessionToken = newToken,
                accountName = "新成员",
                ledgerId = "L_family",
                ledgerName = "家庭账本",
                deviceName = "Pixel 9",
                role = "member",
            ),
            listLedgersResult = LedgerListResponseDto(
                ledgers = listOf(ledgerDto("L_family", "家庭账本", role = "member")),
            ),
        )
        val store = LedgerFakeSettingsStore()
        val tokenStore = LedgerFakeTokenStore()
        val apiFactory = LedgerStubApiFactory(api)
        val repo = LedgerRepository(
            apiClient = apiFactory,
            settingsStore = store,
            tokenStore = tokenStore,
            expenseDao = LedgerFakeDao(),
        )

        val summary = repo.acceptInvitation(
            inviteToken = "inv_JOIN",
            accountName = "新成员",
            deviceName = "Pixel 9",
            serverUrlOverride = "https://join.example.com/",
        ).getOrThrow()

        assertEquals("L_family", summary.ledgerId)
        assertEquals("member", summary.role)
        // Trailing slash trimmed BEFORE the request was built.
        assertEquals("https://join.example.com", apiFactory.baseUrls.first())
        // Unbound accept attaches no token (the override host never sees a
        // stored credential).
        assertNull(apiFactory.tokenProviders.first().invoke())
        // Binding persisted: URL + rotated token + identity, device unlocked.
        assertEquals("https://join.example.com", store.serverUrl())
        assertEquals(newToken, tokenStore.getToken())
        assertEquals("L_family", store.activeLedgerId())
        assertEquals("新成员", store.capturedAccountName)
        assertEquals("member", store.capturedRole)
        assertTrue(store.unlockedMarked)
    }

    @Test
    fun acceptInvitationWithoutOverrideStillRequiresBoundServer() = runTest {
        // No override + nothing persisted = the historic error, and the
        // request never leaves the device.
        val api = StubApi()
        val store = LedgerFakeSettingsStore()
        val tokenStore = LedgerFakeTokenStore()
        val repo = LedgerRepository(
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
    fun acceptInvitationWithOverrideNeverAttachesStoredTokenToOverrideHost() = runTest {
        // Security contract: an override is a caller-supplied host. Even when
        // this device happens to hold a binding (no UI path today, but the
        // repository API allows it), the stored token must NOT be attached to
        // a request leaving for the override host.
        val api = StubApi(
            acceptResult = InvitationAcceptResponseDto(
                sessionToken = "tk_other_server",
                accountName = "新成员",
                ledgerId = "L_other",
                ledgerName = "另一台账本",
                deviceName = "Pixel 9",
                role = "member",
            ),
        )
        val store = LedgerFakeSettingsStore().apply { saveServerUrl("https://old.example.com") }
        val tokenStore = LedgerFakeTokenStore().apply { saveToken("old-token") }
        val apiFactory = LedgerStubApiFactory(api)
        val repo = LedgerRepository(
            apiClient = apiFactory,
            settingsStore = store,
            tokenStore = tokenStore,
            expenseDao = LedgerFakeDao(),
        )

        repo.acceptInvitation(
            inviteToken = "inv_SWITCH",
            accountName = "新成员",
            deviceName = "Pixel 9",
            serverUrlOverride = "https://new.example.com",
        ).getOrThrow()

        assertEquals("https://new.example.com", apiFactory.baseUrls.first())
        // The pre-existing "old-token" never rides along to the new host.
        assertNull(apiFactory.tokenProviders.first().invoke())
        // The binding switched to the override host.
        assertEquals("https://new.example.com", store.serverUrl())
        assertEquals("tk_other_server", tokenStore.getToken())
    }

    @Test
    fun previewInvitationWithServerUrlOverrideWorksUnboundAndPersistsNothing() = runTest {
        val api = StubApi(
            previewResult = InvitationPreviewResponseDto(
                ledgerId = "L_family",
                ledgerName = "家庭账本",
                role = "member",
                expiresAt = "2026-07-01T00:00:00Z",
            ),
        )
        val store = LedgerFakeSettingsStore()
        val tokenStore = LedgerFakeTokenStore()
        val apiFactory = LedgerStubApiFactory(api)
        val repo = LedgerRepository(
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