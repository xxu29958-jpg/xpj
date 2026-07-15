package com.ticketbox.data.repository

import com.ticketbox.data.local.LegacySessionProjectionStore
import com.ticketbox.data.local.PersistedLedgerIdentity
import com.ticketbox.data.local.PersistedSessionProjection
import com.ticketbox.security.DeviceEnrollmentIntent
import com.ticketbox.security.LocalSessionBindingUpdate
import com.ticketbox.security.LocalSessionIdentity
import com.ticketbox.security.LocalSessionRecord
import com.ticketbox.security.StoredSessionToken
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class LocalSessionStoreTest {
    @Test
    fun existingCanonicalSessionWinsAndRetiresLegacyProjection() = runTest {
        val current = localSession(
            serverUrl = "https://new.example.com",
            ledgerId = "ledger-new",
            token = "new-token",
        )
        val sessions = InMemoryLocalSessionStore(current)
        val legacy = FakeLegacySessionProjectionStore(
            projection(
                serverUrl = "https://old.example.com",
                ledgerId = "ledger-old",
            ),
        )

        reconcileLocalSession(
            legacyProjectionStore = legacy,
            sessionStore = sessions,
            legacyCredential = StoredSessionToken("old-token"),
        )

        assertEquals(current, sessions.currentSession())
        assertNull(legacy.readLegacySessionProjection())
        assertEquals(1, legacy.clearCount)
    }

    @Test
    fun completeLegacyTupleMigratesOnceToCanonicalSession() = runTest {
        val legacy = FakeLegacySessionProjectionStore(
            projection(
                serverUrl = "https://API.EXAMPLE.COM:443",
                ledgerId = "ledger-a",
            ),
        )
        val sessions = InMemoryLocalSessionStore()

        reconcileLocalSession(
            legacyProjectionStore = legacy,
            sessionStore = sessions,
            legacyCredential = StoredSessionToken("legacy-token"),
        )

        val migrated = sessions.currentSession()
        assertEquals("https://api.example.com", migrated?.serverUrl)
        assertEquals("ledger-a", migrated?.identity?.ledgerId)
        assertEquals("legacy-token", migrated?.credential?.token)
        assertNull(legacy.readLegacySessionProjection())
    }

    @Test
    fun partialLegacyTupleFailsClosedInsteadOfGuessingIdentity() = runTest {
        val legacy = FakeLegacySessionProjectionStore(null)
        val sessions = InMemoryLocalSessionStore()

        reconcileLocalSession(
            legacyProjectionStore = legacy,
            sessionStore = sessions,
            legacyCredential = StoredSessionToken("orphan-token"),
        )

        assertFalse(sessions.hasPersistedSessionState())
        assertNull(sessions.currentSession())
        assertEquals(1, legacy.clearCount)
    }

    @Test
    fun pendingEnrollmentSurvivesStartupReconciliationWithoutSession() = runTest {
        val sessions = InMemoryLocalSessionStore()
        val pending = sessions.beginOrReuseDeviceEnrollment(
            DeviceEnrollmentIntent.Pairing(
                serverUrl = "https://api.example.com",
                pairingCode = "ABCD-EFGH",
                deviceName = "Pixel",
            ),
        )
        val legacy = FakeLegacySessionProjectionStore(null)

        reconcileLocalSession(
            legacyProjectionStore = legacy,
            sessionStore = sessions,
            legacyCredential = null,
        )

        assertNull(sessions.currentSession())
        assertEquals(pending, sessions.pendingDeviceEnrollment())
        assertTrue(sessions.hasPersistedSessionState())
        assertEquals(1, legacy.clearCount)
    }

    @Test
    fun bindingUpdatePreservesConcurrentSessionRefresh() = runTest {
        val initial = localSession(
            serverUrl = "https://api.example.com",
            ledgerId = "ledger-a",
            token = "token-one",
        )
        val sessions = InMemoryLocalSessionStore(initial)

        val refresh = assertNotNull(
            sessions.sessionRefresh.beginOrReuse(
                expectedSessionGeneration = initial.sessionGeneration,
                expectedToken = "token-one",
            ),
        )
        assertTrue(
            sessions.sessionRefresh.completeIfCurrent(
                expectedSessionGeneration = initial.sessionGeneration,
                expectedToken = "token-one",
                refreshAttemptId = refresh.attemptId,
                replacement = StoredSessionToken("token-two"),
            ),
        )
        assertTrue(
            sessions.updateBindingIfCurrent(
                LocalSessionBindingUpdate(
                    expectedVersion = initial.version,
                    bindingRevision = "binding-ledger-b",
                    serverId = initial.serverId,
                    dataGeneration = initial.dataGeneration,
                    serverUrl = initial.serverUrl,
                    identity = initial.identity.copy(ledgerId = "ledger-b", ledgerName = "账本 B"),
                ),
            ),
        )

        val updated = sessions.currentSession()
        assertEquals(initial.sessionGeneration, updated?.sessionGeneration)
        assertEquals("binding-ledger-b", updated?.bindingRevision)
        assertEquals("token-two", updated?.credential?.token)
    }

    private fun projection(serverUrl: String, ledgerId: String) = PersistedSessionProjection(
        serverUrl = serverUrl,
        identity = PersistedLedgerIdentity(
            accountName = "我",
            ledgerId = ledgerId,
            ledgerName = ledgerId,
            deviceName = "Pixel",
            role = "owner",
            boundAt = "2026-07-14T00:00:00Z",
        ),
    )

    private fun localSession(serverUrl: String, ledgerId: String, token: String) =
        LocalSessionRecord(
            sessionGeneration = "session-$ledgerId",
            bindingRevision = "binding-$ledgerId",
            serverUrl = serverUrl,
            credential = StoredSessionToken(token),
            identity = LocalSessionIdentity(
                accountName = "我",
                ledgerId = ledgerId,
                ledgerName = ledgerId,
                deviceName = "Pixel",
                role = "owner",
                boundAt = "2026-07-14T00:00:00Z",
            ),
        )
}

private class FakeLegacySessionProjectionStore(
    private var projection: PersistedSessionProjection?,
) : LegacySessionProjectionStore {
    var clearCount: Int = 0
        private set

    override fun readLegacySessionProjection(): PersistedSessionProjection? = projection

    override fun clearLegacySessionProjection() {
        projection = null
        clearCount += 1
    }
}
