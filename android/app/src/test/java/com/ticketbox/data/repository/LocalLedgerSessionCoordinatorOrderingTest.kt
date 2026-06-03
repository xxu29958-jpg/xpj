package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationType
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

/**
 * ADR-0038 PR-2g.3 codex round-9 follow-up (round-10): ordering
 * invariant for the outbox session-boundary fix.
 *
 * The post-claim epoch check in [OutboxDrainEngine.drainOnce] only
 * helps if the epoch is bumped BEFORE credentials change. Otherwise
 * a drain that passes the epoch check while credentials are still
 * old can reach ``dispatcher.dispatch`` AFTER the credentials
 * change, resolve ``apiProvider()`` to the new ApiService, and
 * send the OLD row under the NEW session.
 *
 * These tests pin the contract: session changes run inside
 * [OutboxRepository.withBindingTransition], which blocks dispatch and
 * enqueue while credentials are mutating.
 */
class LocalLedgerSessionCoordinatorOrderingTest {

    @Test
    fun targetLedgerTransitionRunsInsideOutboxBindingBoundary() = runTest {
        val dao = FakePendingMutationDao()
        val settings = FakeTicketboxSettingsStore().apply {
            saveServerUrl("https://old.example.com")
            saveIdentity(
                accountName = "我",
                ledgerId = "old-ledger",
                ledgerName = "旧账本",
                deviceName = "Pixel",
                role = "owner",
                boundAt = "2026-05-01T00:00:00Z",
            )
        }
        val tokens = FakeSessionTokenStore().apply { saveToken("old-token") }
        val expenseDao = FakeExpenseDao()

        var serverUrlAtBoundary: String? = null
        var tokenAtBoundary: String? = null
        val outbox = OutboxRepository(
            dao = dao,
            onClearAll = {
                serverUrlAtBoundary = settings.serverUrl()
                tokenAtBoundary = tokens.getToken()
            },
        )
        // Seed an outbox row so the binding-scoped queue preservation
        // path is exercised.
        outbox.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:1",
            payloadJson = "{}",
            expectedRowVersion = 1L,
        )

        val coordinator = LocalLedgerSessionCoordinator(
            settingsStore = settings,
            tokenStore = tokens,
            expenseDao = expenseDao,
            outbox = outbox,
        )

        coordinator.applyTransition(
            identity = LedgerSessionIdentity(
                accountName = "我",
                ledgerId = "new-ledger",
                ledgerName = "新账本",
                deviceName = "Pixel",
                role = "owner",
                boundAt = "2026-05-04T12:00:00Z",
            ),
            serverUrl = "https://new.example.com",
            sessionToken = "new-token",
            cacheInvalidation = LedgerCacheInvalidation.TargetLedger,
        )

        assertNotNull(serverUrlAtBoundary, "onClearAll must have fired")
        assertEquals("https://new.example.com", settings.serverUrl())
        assertEquals("new-token", tokens.getToken())
        assertEquals("https://new.example.com", serverUrlAtBoundary)
        assertEquals("new-token", tokenAtBoundary)
        // Binding-scoped outbox rows are preserved; the new binding
        // cannot drain them because repository queries now filter by
        // serverUrl + ledgerId.
        assertEquals(1, dao.rows.size)
    }

    @Test
    fun allLedgersTransitionRunsInsideOutboxBindingBoundary() = runTest {
        val dao = FakePendingMutationDao()
        val settings = FakeTicketboxSettingsStore().apply {
            saveServerUrl("https://old.example.com")
        }
        val tokens = FakeSessionTokenStore().apply { saveToken("old-token") }

        var serverUrlAtBoundary: String? = null
        val outbox = OutboxRepository(
            dao = dao,
            onClearAll = { serverUrlAtBoundary = settings.serverUrl() },
        )
        outbox.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:7",
            payloadJson = "{}",
            expectedRowVersion = 1L,
        )

        val coordinator = LocalLedgerSessionCoordinator(
            settingsStore = settings,
            tokenStore = tokens,
            expenseDao = FakeExpenseDao(),
            outbox = outbox,
        )

        coordinator.applyTransition(
            identity = LedgerSessionIdentity(
                accountName = "我",
                ledgerId = "new",
                ledgerName = "new",
                deviceName = "Pixel",
                role = "owner",
                boundAt = "2026-05-04T12:00:00Z",
            ),
            serverUrl = "https://new.example.com",
            sessionToken = "new-token",
            cacheInvalidation = LedgerCacheInvalidation.AllLedgers,
        )

        assertEquals("https://new.example.com", serverUrlAtBoundary)
    }

    @Test
    fun inFlightDispatchBlocksSessionTransitionUntilDone() = runTest(UnconfinedTestDispatcher()) {
        // [codex round-11 P1] dispatch lease test.
        //
        // Scenario the round-10 ordering alone couldn't close: the
        // drain engine has passed the post-claim epoch check but
        // hasn't yet resolved apiProvider() inside dispatch (or
        // hasn't yet hit the OkHttp interceptor's lazy token read).
        // If a concurrent session transition fires here, without
        // the lease the dispatch would resume with the NEW
        // credentials.
        //
        // We pin the contract via a dispatcher that suspends mid-
        // dispatch on a CompletableDeferred. While suspended:
        //   - drain holds the dispatch lease
        //   - we launch coordinator.applyTransition concurrently
        //   - we assert credentials are STILL old (the lease
        //     blocks clearAll, which blocks the credential write
        //     that follows it in applyTransition)
        // Then we release the dispatch, both flows complete, and
        // credentials end up at NEW.
        val dao = FakePendingMutationDao()
        val settings = FakeTicketboxSettingsStore().apply {
            saveServerUrl("https://old.example.com")
        }
        val tokens = FakeSessionTokenStore().apply { saveToken("old-token") }
        val outbox = OutboxRepository(dao = dao)

        val dispatchStarted = CompletableDeferred<Unit>()
        val dispatchCanProceed = CompletableDeferred<Unit>()
        var serverUrlAtDispatchTime: String? = null
        var tokenAtDispatchTime: String? = null
        val dispatcher = object : OutboxMutationDispatcher {
            override val type = PendingMutationType.PatchExpense
            override suspend fun dispatch(row: OutboxRow): DispatchResult {
                serverUrlAtDispatchTime = settings.serverUrl()
                tokenAtDispatchTime = tokens.getToken()
                dispatchStarted.complete(Unit)
                // Hold the lease here. While we wait, applyTransition
                // will try the binding transition, wait for the lease,
                // and block credential writes.
                dispatchCanProceed.await()
                return DispatchResult.Success()
            }
        }
        val engine = OutboxDrainEngine(outbox, listOf(dispatcher))
        outbox.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 2L)

        val coordinator = LocalLedgerSessionCoordinator(
            settingsStore = settings,
            tokenStore = tokens,
            expenseDao = FakeExpenseDao(),
            outbox = outbox,
        )

        val drainJob = launch { engine.drainOnce() }
        // Wait until drain has entered dispatch (lease held).
        dispatchStarted.await()

        // Launch the transition concurrently. The binding transition
        // will try to acquire the lease and block; credential writes
        // won't run until the lease releases.
        val transitionJob = launch {
            coordinator.applyTransition(
                identity = LedgerSessionIdentity(
                    accountName = "我",
                    ledgerId = "new",
                    ledgerName = "new",
                    deviceName = "Pixel",
                    role = "owner",
                    boundAt = "2026-05-04T12:00:00Z",
                ),
                serverUrl = "https://new.example.com",
                sessionToken = "new-token",
                cacheInvalidation = LedgerCacheInvalidation.AllLedgers,
            )
        }
        // Give the transition coroutine a chance to attempt the
        // lease acquire. UnconfinedTestDispatcher dispatches eagerly
        // so by the time we get here the launch has at least begun.
        // The transition coroutine is suspended on the lease at this
        // point (or will be very shortly).

        // While the drain holds the lease, credentials must NOT have
        // been rewritten. This is the round-11 invariant: lazy
        // credential reads inside dispatch can't see post-transition
        // values.
        assertEquals(
            "https://old.example.com",
            settings.serverUrl(),
            "credentials must not change while a dispatch holds the lease",
        )
        assertEquals(
            "old-token",
            tokens.getToken(),
            "token must not change while a dispatch holds the lease",
        )

        // Release the dispatch.
        dispatchCanProceed.complete(Unit)
        drainJob.join()
        transitionJob.join()

        // Dispatch saw OLD credentials (proved by capture at
        // dispatch start).
        assertEquals("https://old.example.com", serverUrlAtDispatchTime)
        assertEquals("old-token", tokenAtDispatchTime)
        // After the lease released, transition completed and the
        // new credentials are in place.
        assertEquals("https://new.example.com", settings.serverUrl())
        assertEquals("new-token", tokens.getToken())
    }

    @Test
    fun noneCacheInvalidation_doesNotClearOutbox() = runTest {
        // The None branch is for transitions that DON'T require
        // dropping the local cache (e.g. token refresh on the same
        // ledger). Outbox should stay intact.
        val dao = FakePendingMutationDao()
        val settings = FakeTicketboxSettingsStore().apply {
            saveServerUrl("https://example.com")
        }
        val tokens = FakeSessionTokenStore().apply { saveToken("old-token") }
        var clearAllFired = false
        val outbox = OutboxRepository(
            dao = dao,
            onClearAll = { clearAllFired = true },
        )
        outbox.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:1",
            payloadJson = "{}",
            expectedRowVersion = 1L,
        )

        val coordinator = LocalLedgerSessionCoordinator(
            settingsStore = settings,
            tokenStore = tokens,
            expenseDao = FakeExpenseDao(),
            outbox = outbox,
        )

        coordinator.applyTransition(
            identity = LedgerSessionIdentity(
                accountName = "我",
                ledgerId = "same-ledger",
                ledgerName = "same",
                deviceName = "Pixel",
                role = "owner",
                boundAt = "2026-05-04T12:00:00Z",
            ),
            sessionToken = "refreshed-token",
            cacheInvalidation = LedgerCacheInvalidation.None,
        )

        assertTrue(!clearAllFired, "None cacheInvalidation must not wipe the outbox")
        assertEquals(1, dao.rows.size, "outbox row should still be there")
    }
}
