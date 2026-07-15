package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.security.LocalSessionIdentity
import com.ticketbox.security.LocalSessionRecord
import com.ticketbox.security.StoredSessionToken
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.launch
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull

/** Pins session transitions to the same lease that protects outbox enqueue and dispatch. */
class LocalLedgerSessionCoordinatorOrderingTest {

    @Test
    fun newSessionRunsInsideOutboxBindingBoundary() = runTest {
        val dao = FakePendingMutationDao()
        val settings = FakeTicketboxSettingsStore()
        val sessionStore = InMemoryLocalSessionStore(
            session(serverUrl = "https://old.example.com", ledgerId = "old-ledger", token = "old-token"),
        )
        var sessionAtBoundary: LocalSessionRecord? = null
        val outbox = outboxBoundTo(sessionStore, dao) {
            sessionAtBoundary = sessionStore.currentSession()
        }
        outbox.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:1",
            payloadJson = "{}",
            expectedRowVersion = 1L,
        )
        val coordinator = LocalLedgerSessionCoordinator(
            settingsStore = settings,
            sessionStore = sessionStore,
            expenseDao = FakeExpenseDao(),
            outbox = outbox,
        )

        coordinator.applyTransition(
            LedgerSessionTransition(
                change = LocalSessionChange.EstablishSession,
                identity = ledgerIdentity(ledgerId = "new-ledger", ledgerName = "新账本"),
                serverId = NEW_SERVER_ID,
                dataGeneration = NEW_DATA_GENERATION,
                serverUrl = "https://new.example.com",
                sessionToken = "new-token",
                cacheInvalidation = LedgerCacheInvalidation.TargetLedger,
            ),
        )

        val committed = assertNotNull(sessionAtBoundary)
        assertEquals("https://new.example.com", committed.serverUrl)
        assertEquals("new-token", committed.credential.token)
        assertEquals("new-ledger", committed.identity.ledgerId)
        assertEquals(1, dao.rows.size, "old-session intent must be preserved for explicit recovery")
        assertEquals(0, outbox.dequeueNextRunnable().size, "new session must not see the old binding")
    }

    @Test
    fun canonicalServerAliasMigrationKeepsSameLedgerOutboxVisible() = runTest {
        val dao = FakePendingMutationDao()
        val sessionStore = InMemoryLocalSessionStore(
            session(serverUrl = "https://API.EXAMPLE.COM:443", ledgerId = "same-ledger", token = "old-token"),
        )
        val outbox = outboxBoundTo(sessionStore, dao)
        val queuedId = outbox.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:7",
            payloadJson = "{}",
            expectedRowVersion = 1L,
        )
        dao.rows[queuedId] = dao.rows.getValue(queuedId).copy(
            serverUrl = "https://API.EXAMPLE.COM:443",
        )

        val restartedOutbox = outboxBoundTo(sessionStore, dao)
        assertEquals("expense:7", restartedOutbox.dequeueNextRunnable().single().targetId)
        assertEquals("https://api.example.com", dao.rows.getValue(queuedId).serverUrl)
    }

    @OptIn(ExperimentalCoroutinesApi::class)
    @Test
    fun inFlightDispatchBlocksSessionTransitionUntilDone() = runTest(UnconfinedTestDispatcher()) {
        val dao = FakePendingMutationDao()
        val settings = FakeTicketboxSettingsStore()
        val sessionStore = InMemoryLocalSessionStore(
            session(serverUrl = "https://old.example.com", ledgerId = "old", token = "old-token"),
        )
        val outbox = outboxBoundTo(sessionStore, dao)
        val dispatchStarted = CompletableDeferred<Unit>()
        val dispatchCanProceed = CompletableDeferred<Unit>()
        var sessionAtDispatchTime: LocalSessionRecord? = null
        val dispatcher = object : OutboxMutationDispatcher {
            override val type = PendingMutationType.PatchExpense

            override suspend fun dispatch(row: OutboxRow): DispatchResult {
                sessionAtDispatchTime = sessionStore.currentSession()
                dispatchStarted.complete(Unit)
                dispatchCanProceed.await()
                return DispatchResult.Success()
            }
        }
        val engine = OutboxDrainEngine(outbox, listOf(dispatcher))
        outbox.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 2L)
        val coordinator = LocalLedgerSessionCoordinator(
            settingsStore = settings,
            sessionStore = sessionStore,
            expenseDao = FakeExpenseDao(),
            outbox = outbox,
        )

        val drainJob = launch { engine.drainOnce() }
        dispatchStarted.await()
        val transitionJob = launch {
            coordinator.applyTransition(
                LedgerSessionTransition(
                    change = LocalSessionChange.EstablishSession,
                    identity = ledgerIdentity(ledgerId = "new", ledgerName = "new"),
                    serverId = NEW_SERVER_ID,
                    dataGeneration = NEW_DATA_GENERATION,
                    serverUrl = "https://new.example.com",
                    sessionToken = "new-token",
                    cacheInvalidation = LedgerCacheInvalidation.AllLedgers,
                ),
            )
        }

        assertEquals("https://old.example.com", sessionStore.currentSession()?.serverUrl)
        assertEquals("old-token", sessionStore.currentSession()?.credential?.token)

        dispatchCanProceed.complete(Unit)
        drainJob.join()
        transitionJob.join()

        assertEquals("https://old.example.com", sessionAtDispatchTime?.serverUrl)
        assertEquals("old-token", sessionAtDispatchTime?.credential?.token)
        assertEquals("https://new.example.com", sessionStore.currentSession()?.serverUrl)
        assertEquals("new-token", sessionStore.currentSession()?.credential?.token)
    }

    @Test
    fun credentialRotationPreservesLogicalBindingAndDoesNotSignalSessionBoundary() = runTest {
        val dao = FakePendingMutationDao()
        val original = session(
            serverUrl = "https://example.com",
            ledgerId = "same-ledger",
            token = "old-token",
        )
        val sessionStore = InMemoryLocalSessionStore(original)
        var boundarySignalled = false
        val outbox = outboxBoundTo(sessionStore, dao) { boundarySignalled = true }
        outbox.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 1L)

        val refresh = assertNotNull(
            sessionStore.sessionRefresh.beginOrReuse(
                expectedSessionGeneration = original.sessionGeneration,
                expectedToken = original.credential.token,
            ),
        )
        val rotated = sessionStore.sessionRefresh.completeIfCurrent(
            expectedSessionGeneration = original.sessionGeneration,
            expectedToken = original.credential.token,
            refreshAttemptId = refresh.attemptId,
            replacement = StoredSessionToken("refreshed-token"),
        )

        assertEquals(true, rotated)
        assertFalse(boundarySignalled)
        assertEquals(original.sessionGeneration, sessionStore.currentSession()?.sessionGeneration)
        assertEquals(original.bindingRevision, sessionStore.currentSession()?.bindingRevision)
        assertEquals("refreshed-token", sessionStore.currentSession()?.credential?.token)
        assertEquals(1, dao.rows.size)
    }

    @Test
    fun signOutPreservesOfflineIntentAsQuarantine() = runTest {
        val dao = FakePendingMutationDao()
        val sessionStore = InMemoryLocalSessionStore(
            session(serverUrl = "https://api.example.com", ledgerId = "owner", token = "old-token"),
        )
        val outbox = outboxBoundTo(sessionStore, dao)
        outbox.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 1L)
        val coordinator = LocalLedgerSessionCoordinator(
            settingsStore = FakeTicketboxSettingsStore(),
            sessionStore = sessionStore,
            expenseDao = FakeExpenseDao(),
            outbox = outbox,
        )

        coordinator.clearSession()

        assertEquals(1, dao.rows.size, "sign-out must not silently discard a financial intent")
        assertEquals(0, outbox.dequeueNextRunnable().size)
        assertEquals(1, outbox.observeStatus().first().quarantinedCount)
    }

    private fun outboxBoundTo(
        sessionStore: InMemoryLocalSessionStore,
        dao: FakePendingMutationDao,
        onBindingTransition: () -> Unit = {},
    ): OutboxRepository = testOutboxRepository(
        dao = dao,
        bindingProvider = {
            sessionStore.currentSession()?.let {
                OutboxBinding(
                    serverUrl = it.serverUrl,
                    ledgerId = it.identity.ledgerId,
                    owner = OutboxOwnerIdentity.fromOrNull(
                        serverId = it.serverId,
                        dataGeneration = it.dataGeneration,
                        accountPublicId = it.identity.accountPublicId,
                        devicePublicId = it.identity.devicePublicId,
                    ),
                )
            } ?: OutboxBinding.DEFAULT
        },
        onClearAll = onBindingTransition,
    )

    private fun session(
        serverUrl: String,
        ledgerId: String,
        token: String,
    ): LocalSessionRecord = LocalSessionRecord(
        sessionGeneration = "session-old",
        bindingRevision = "binding-old",
        serverId = SERVER_ID,
        dataGeneration = DATA_GENERATION,
        serverUrl = serverUrl,
        credential = StoredSessionToken(token),
        identity = LocalSessionIdentity(
            accountPublicId = ACCOUNT_PUBLIC_ID,
            devicePublicId = DEVICE_PUBLIC_ID,
            accountName = "我",
            ledgerId = ledgerId,
            ledgerName = ledgerId,
            deviceName = "Pixel",
            role = "owner",
            boundAt = "2026-05-01T00:00:00Z",
        ),
    )

    private fun ledgerIdentity(ledgerId: String, ledgerName: String): LedgerSessionIdentity =
        LedgerSessionIdentity(
            accountPublicId = ACCOUNT_PUBLIC_ID,
            devicePublicId = DEVICE_PUBLIC_ID,
            accountName = "我",
            ledgerId = ledgerId,
            ledgerName = ledgerName,
            deviceName = "Pixel",
            role = "owner",
            boundAt = "2026-05-04T12:00:00Z",
        )

    companion object {
        private const val SERVER_ID = "00000000-0000-0000-0000-000000000011"
        private const val DATA_GENERATION = "00000000-0000-0000-0000-000000000012"
        private const val ACCOUNT_PUBLIC_ID = "00000000-0000-0000-0000-000000000013"
        private const val DEVICE_PUBLIC_ID = "00000000-0000-0000-0000-000000000014"
        private const val NEW_SERVER_ID = "00000000-0000-0000-0000-000000000021"
        private const val NEW_DATA_GENERATION = "00000000-0000-0000-0000-000000000022"
    }
}
