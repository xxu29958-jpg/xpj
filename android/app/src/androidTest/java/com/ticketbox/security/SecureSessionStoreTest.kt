package com.ticketbox.security

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class SecureSessionStoreTest {
    private val context
        get() = InstrumentationRegistry.getInstrumentation().targetContext

    @After
    fun clearSession() = runBlocking {
        SecureSessionStore(context).clearSession()
    }

    @Test
    fun completeSessionPersistsAndStaleCredentialCannotOverwriteIt() = runBlocking {
        val firstProcess = SecureSessionStore(context)
        firstProcess.clearSession()
        firstProcess.establishSession(session(token = "token-one"))

        val reconstructed = SecureSessionStore(context)
        val beforeRotation = requireNotNull(reconstructed.currentSession())
        assertEquals("https://api.example.com", beforeRotation.serverUrl)
        assertEquals("ledger-a", beforeRotation.identity.ledgerId)
        assertEquals("token-one", beforeRotation.credential.token)

        val refresh = requireNotNull(
            reconstructed.sessionRefresh.beginOrReuse(
                expectedSessionGeneration = beforeRotation.sessionGeneration,
                expectedToken = "token-one",
            ),
        )
        assertFalse(
            firstProcess.sessionRefresh.completeIfCurrent(
                expectedSessionGeneration = beforeRotation.sessionGeneration,
                expectedToken = "token-one",
                refreshAttemptId = "not-the-current-attempt",
                replacement = StoredSessionToken("stale-token"),
            ),
        )
        assertTrue(
            reconstructed.sessionRefresh.completeIfCurrent(
                expectedSessionGeneration = beforeRotation.sessionGeneration,
                expectedToken = "token-one",
                refreshAttemptId = refresh.attemptId,
                replacement = StoredSessionToken("token-two"),
            ),
        )
        assertFalse(
            firstProcess.sessionRefresh.completeIfCurrent(
                expectedSessionGeneration = beforeRotation.sessionGeneration,
                expectedToken = "token-one",
                refreshAttemptId = refresh.attemptId,
                replacement = StoredSessionToken("stale-token"),
            ),
        )

        val afterRotation = requireNotNull(SecureSessionStore(context).currentSession())
        assertEquals("token-two", afterRotation.credential.token)
        assertEquals(beforeRotation.version, afterRotation.version)
    }

    @Test
    fun bindingUpdateAfterRotationKeepsNewestCredentialAcrossReconstruction() = runBlocking {
        val store = SecureSessionStore(context)
        store.clearSession()
        val initial = session(token = "token-one")
        store.establishSession(initial)

        val refresh = requireNotNull(
            store.sessionRefresh.beginOrReuse(
                expectedSessionGeneration = initial.sessionGeneration,
                expectedToken = "token-one",
            ),
        )
        assertTrue(
            store.sessionRefresh.completeIfCurrent(
                expectedSessionGeneration = initial.sessionGeneration,
                expectedToken = "token-one",
                refreshAttemptId = refresh.attemptId,
                replacement = StoredSessionToken("token-two"),
            ),
        )
        assertTrue(
            store.updateBindingIfCurrent(
                LocalSessionBindingUpdate(
                    expectedVersion = initial.version,
                    bindingRevision = "binding-two",
                    serverId = initial.serverId,
                    dataGeneration = initial.dataGeneration,
                    serverUrl = initial.serverUrl,
                    identity = initial.identity.copy(ledgerId = "ledger-b", ledgerName = "账本 B"),
                ),
            ),
        )

        val reconstructed = requireNotNull(SecureSessionStore(context).currentSession())
        assertEquals(initial.sessionGeneration, reconstructed.sessionGeneration)
        assertEquals("binding-two", reconstructed.bindingRevision)
        assertEquals("ledger-b", reconstructed.identity.ledgerId)
        assertEquals("token-two", reconstructed.credential.token)
    }

    @Test
    fun invitationEnrollmentSurvivesReconstructionAndCommitsWithSession() = runBlocking {
        val firstProcess = SecureSessionStore(context)
        firstProcess.clearSession()
        val attempt = firstProcess.beginOrReuseDeviceEnrollment(
            DeviceEnrollmentIntent.Invitation(
                serverUrl = "https://api.example.com",
                inviteToken = "inv_recoverable",
                accountName = "家人",
                deviceName = "Pixel",
            ),
        )

        val reconstructed = SecureSessionStore(context)
        assertEquals(attempt, reconstructed.pendingDeviceEnrollment())

        reconstructed.establishSession(
            session(token = "enrolled-token"),
            completedEnrollmentAttemptId = attempt.attemptId,
        )
        val committed = SecureSessionStore(context)
        assertEquals(null, committed.pendingDeviceEnrollment())
        assertEquals("enrolled-token", committed.currentSession()?.credential?.token)
    }

    @Test
    fun sessionRefreshSurvivesReconstructionAndCommitsWithCredential() = runBlocking {
        val firstProcess = SecureSessionStore(context)
        firstProcess.clearSession()
        val initial = session(token = "token-before-refresh")
        firstProcess.establishSession(initial)
        val attempt = requireNotNull(
            firstProcess.sessionRefresh.beginOrReuse(
                expectedSessionGeneration = initial.sessionGeneration,
                expectedToken = initial.credential.token,
            ),
        )

        val reconstructed = SecureSessionStore(context)
        assertEquals(attempt, reconstructed.sessionRefresh.pending())
        assertTrue(
            reconstructed.sessionRefresh.completeIfCurrent(
                expectedSessionGeneration = initial.sessionGeneration,
                expectedToken = initial.credential.token,
                refreshAttemptId = attempt.attemptId,
                replacement = StoredSessionToken("token-after-refresh"),
            ),
        )

        val committed = SecureSessionStore(context)
        assertEquals(null, committed.sessionRefresh.pending())
        assertEquals("token-after-refresh", committed.currentSession()?.credential?.token)
        assertEquals(initial.version, committed.currentSession()?.version)
    }

    @Test
    fun multipleConsumersShareCommittedSnapshotAndFlow() = runBlocking {
        val appConsumer = SecureSessionStore(context)
        appConsumer.clearSession()
        val serviceConsumer = SecureSessionStore(context)
        val observed = async(start = CoroutineStart.UNDISPATCHED) {
            withTimeout(5_000) {
                appConsumer.observeSession().filterNotNull().first()
            }
        }

        serviceConsumer.establishSession(session(token = "service-token"))

        assertEquals("service-token", observed.await().credential.token)
        assertEquals("service-token", appConsumer.currentSession()?.credential?.token)
        serviceConsumer.clearSession()
        assertNull(appConsumer.currentSession())
    }

    private fun session(token: String) = LocalSessionRecord(
        sessionGeneration = "session-one",
        bindingRevision = "binding-one",
        serverId = "70000000-0000-0000-0000-000000000001",
        dataGeneration = "70000000-0000-0000-0000-000000000002",
        serverUrl = "https://api.example.com",
        credential = StoredSessionToken(token),
        identity = LocalSessionIdentity(
            accountPublicId = "70000000-0000-0000-0000-000000000003",
            devicePublicId = "70000000-0000-0000-0000-000000000004",
            accountName = "我",
            ledgerId = "ledger-a",
            ledgerName = "家庭账本",
            deviceName = "Pixel",
            role = "owner",
            boundAt = "2026-07-14T00:00:00Z",
        ),
    )
}
