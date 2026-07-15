package com.ticketbox.data.repository

import com.ticketbox.data.local.ExpenseEntity
import com.ticketbox.security.LocalSessionIdentity
import com.ticketbox.security.LocalSessionRecord
import com.ticketbox.security.StoredSessionToken
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class ExpenseRepositoryBindServerTest {
    @Test
    fun bindSavesSessionAndIdentityBeforeConfirmedRestoreFailure() = runTest {
        val events = mutableListOf<String>()
        val settingsStore = FakeTicketboxSettingsStore(events).apply {
            saveLastConfirmedSyncAt("2026-05-01T00:00:00Z")
        }
        val tokenStore = TestSessionFixture(events)
        val apiService = FakeApiService(events, confirmedFailuresRemaining = 1)
        val repository = bindRepository(
            dao = FakeExpenseDao(),
            apiFactory = FakeApiServiceFactory(apiService),
            settingsStore = settingsStore,
            tokenStore = tokenStore,
        )

        val result = repository.bindServer("https://api.example.com/", "123456").getOrThrow()

        assertTrue(result.confirmedRestoreFailed)
        val session = assertNotNull(tokenStore.sessionStore.currentSession())
        assertEquals("https://api.example.com", session.serverUrl)
        assertEquals("session-token", session.credential.token)
        assertEquals("我", session.identity.accountName)
        assertEquals("我的小票夹", session.identity.ledgerName)
        assertEquals("Android Test Device", session.identity.deviceName)
        assertEquals("owner", session.identity.role)
        assertNull(settingsStore.lastConfirmedSyncAt())
    }

    @Test
    fun bindFromUnboundStateClearsStaleLocalAccountCache() = runTest {
        val events = mutableListOf<String>()
        val dao = FakeExpenseDao(events)
        seedStaleAccountCache(dao)
        val settingsStore = FakeTicketboxSettingsStore(events).apply {
            saveAvailableLedgersJson("""[{"ledger_id":"old","name":"Old","role":"owner"}]""")
        }
        val tokenStore = TestSessionFixture(events).apply {
            saveToken("old-session-token")
            clear()
        }
        val apiService = FakeApiService(events, confirmedFailuresRemaining = 1)
        val apiFactory = FakeApiServiceFactory(apiService)
        val repository = bindRepository(
            dao = dao,
            apiFactory = apiFactory,
            settingsStore = settingsStore,
            tokenStore = tokenStore,
        )

        val result = repository.bindServer("https://new.example.com", "123456").getOrThrow()

        assertTrue(result.confirmedRestoreFailed)
        assertNull(apiFactory.tokenValues.first())
        assertEquals("session-token", apiFactory.tokenValues.last())
        assertTrue(dao.getConfirmed("owner").isEmpty())
        assertTrue(dao.getConfirmed("family").isEmpty())
        assertNull(settingsStore.availableLedgersJson())
        assertTrue(events.indexOf("clear") < events.indexOf("syncConfirmed"))
    }

    private suspend fun seedStaleAccountCache(dao: FakeExpenseDao) {
        dao.insert(
            ExpenseEntity(
                ledgerId = "owner",
                serverId = 99,
                publicId = "old-server-expense",
                amountCents = 1200,
                merchant = "旧服务器缓存",
                category = "餐饮",
                note = null,
                source = "旧绑定",
                thumbnailPath = null,
                imageHash = null,
                rawText = null,
                duplicateStatus = "none",
                duplicateOfId = null,
                duplicateReason = null,
                tags = null,
                valueScore = null,
                regretScore = null,
                status = "confirmed",
                expenseTime = "2026-05-01T00:00:00Z",
                createdAt = "2026-05-01T00:00:00Z",
                confirmedAt = "2026-05-01T00:00:00Z",
                updatedAt = "2026-05-01T00:00:00Z",
                rowVersion = 1L,
            ),
        )
        dao.insert(
            cachedConfirmedEntity(
                serverId = 100,
                publicId = "old-other-ledger",
                merchant = "旧家庭",
                ledgerId = "family",
            ),
        )
    }

    @Test
    fun bindCannotOverwriteAnActiveSessionOrLeavePendingEnrollment() = runTest {
        val tokenStore = TestSessionFixture().apply { saveToken("active-token") }
        val apiService = FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0)
        val apiFactory = FakeApiServiceFactory(apiService)
        val repository = bindRepository(
            dao = FakeExpenseDao(),
            apiFactory = apiFactory,
            settingsStore = FakeTicketboxSettingsStore(),
            tokenStore = tokenStore,
        )

        val failure = repository.bindServer(
            "https://other.example.com",
            "123456",
        ).exceptionOrNull()

        assertNotNull(failure)
        assertTrue(failure.message!!.contains("不能直接覆盖"))
        assertEquals("active-token", tokenStore.getToken())
        assertNull(tokenStore.sessionStore.pendingDeviceEnrollment())
        assertTrue(apiFactory.tokenValues.isEmpty())
    }

    @Test
    fun bindRestoreDoesNotWriteOldLedgerRowsAfterLocalLedgerChanges() = runTest {
        val events = mutableListOf<String>()
        val dao = FakeExpenseDao(events)
        val settingsStore = FakeTicketboxSettingsStore(events)
        val tokenStore = TestSessionFixture(events)
        val apiService = FakeApiService(events, confirmedFailuresRemaining = 0)
        apiService.onConfirmedRequest = {
            tokenStore.sessionStore.replaceForFixture(
                LocalSessionRecord(
                    sessionGeneration = "session-family",
                    bindingRevision = "binding-family",
                    serverId = "11111111-1111-4111-8111-111111111111",
                    dataGeneration = "22222222-2222-4222-8222-222222222222",
                    serverUrl = "https://api.example.com",
                    credential = StoredSessionToken("session-family"),
                    identity = LocalSessionIdentity(
                        accountPublicId = "33333333-3333-4333-8333-333333333333",
                        devicePublicId = "55555555-5555-4555-8555-555555555555",
                        accountName = "家人",
                        ledgerId = "family",
                        ledgerName = "家庭账本",
                        deviceName = "Pixel",
                        role = "member",
                        boundAt = "2026-05-01T00:05:00Z",
                    ),
                ),
            )
        }
        val repository = bindRepository(
            dao = dao,
            apiFactory = FakeApiServiceFactory(apiService),
            settingsStore = settingsStore,
            tokenStore = tokenStore,
        )

        val result = repository.bindServer("https://api.example.com", "123456").getOrThrow()

        assertTrue(result.confirmedRestoreFailed)
        assertEquals("family", tokenStore.sessionStore.currentSession()?.identity?.ledgerId)
        assertEquals("session-family", tokenStore.getToken())
        assertTrue(dao.getConfirmed("owner").isEmpty())
        assertTrue(dao.getConfirmed("family").isEmpty())
        assertNull(settingsStore.lastConfirmedSyncAt())
    }

    @Test
    fun manualConfirmedSyncStillWorksAfterBindRestoreFailure() = runTest {
        val events = mutableListOf<String>()
        val dao = FakeExpenseDao()
        val settingsStore = FakeTicketboxSettingsStore(events)
        val tokenStore = TestSessionFixture(events)
        val apiService = FakeApiService(events, confirmedFailuresRemaining = 1)
        val apiFactory = FakeApiServiceFactory(apiService)
        val repository = bindRepository(
            dao = dao,
            apiFactory = apiFactory,
            settingsStore = settingsStore,
            tokenStore = tokenStore,
        )

        val bindResult = repository.bindServer("https://api.example.com", "123456").getOrThrow()
        val syncResult = repository.syncConfirmed().getOrThrow()

        assertTrue(bindResult.confirmedRestoreFailed)
        assertEquals(1, syncResult.size)
        assertEquals("高德", dao.getConfirmed("owner").single().merchant)
        assertEquals("session-token", apiFactory.tokenValues.last())
    }

    @Test
    fun lostPairingResponseKeepsAndReusesOneDurableAttempt() = runTest {
        val settingsStore = FakeTicketboxSettingsStore()
        val tokenStore = TestSessionFixture()
        val apiService = FakeApiService(
            events = mutableListOf(),
            confirmedFailuresRemaining = 0,
            pairFailuresRemaining = 1,
        )
        val repository = bindRepository(
            dao = FakeExpenseDao(),
            apiFactory = FakeApiServiceFactory(apiService),
            settingsStore = settingsStore,
            tokenStore = tokenStore,
        )

        assertTrue(repository.bindServer("https://api.example.com", "123456").isFailure)
        val pending = assertNotNull(tokenStore.sessionStore.pendingDeviceEnrollment())
        assertNull(tokenStore.sessionStore.currentSession())

        val resumed = assertNotNull(repository.resumePendingBinding()).getOrThrow()

        assertTrue(!resumed.confirmedRestoreFailed)
        assertEquals(2, apiService.pairRequests.size)
        assertEquals(
            apiService.pairRequests.first().pairingAttemptId,
            apiService.pairRequests.last().pairingAttemptId,
        )
        assertEquals(
            apiService.pairRequests.first().pairingAttemptSecret,
            apiService.pairRequests.last().pairingAttemptSecret,
        )
        assertEquals(pending.attemptId, apiService.pairRequests.last().pairingAttemptId)
        assertNull(tokenStore.sessionStore.pendingDeviceEnrollment())
        assertEquals("session-token", tokenStore.sessionStore.currentSession()?.credential?.token)
    }

    private fun bindRepository(
        dao: FakeExpenseDao,
        apiFactory: FakeApiServiceFactory,
        settingsStore: FakeTicketboxSettingsStore,
        tokenStore: TestSessionFixture,
    ): ExpenseRepository = ExpenseRepository(
        expenseDao = dao,
        binding = testServerSessionBinding(
            apiClient = apiFactory,
            settingsStore = settingsStore,
            tokenStore = tokenStore,
        ),
        deviceNameProvider = { "Android Test Device" },
    )
}
