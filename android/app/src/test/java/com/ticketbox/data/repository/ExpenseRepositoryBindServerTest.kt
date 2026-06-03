package com.ticketbox.data.repository

import com.ticketbox.data.local.ExpenseEntity
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
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
        val tokenStore = FakeSessionTokenStore(events)
        val apiService = FakeApiService(events, confirmedFailuresRemaining = 1)
        val repository = ExpenseRepository(
            expenseDao = FakeExpenseDao(),
            apiClient = FakeApiServiceFactory(apiService),
            settingsStore = settingsStore,
            tokenStore = tokenStore,
            deviceNameProvider = { "Android Test Device" },
        )

        val result = repository.bindServer("https://api.example.com/", "123456").getOrThrow()

        assertTrue(result.confirmedRestoreFailed)
        assertEquals("https://api.example.com", settingsStore.serverUrl())
        assertEquals("session-token", tokenStore.getToken())
        assertEquals("我", settingsStore.accountName())
        assertEquals("我的小票夹", settingsStore.ledgerName())
        assertEquals("Android Test Device", settingsStore.deviceName())
        assertEquals("owner", settingsStore.role())
        assertNull(settingsStore.lastConfirmedSyncAt())
        assertTrue(settingsStore.isBound())
        assertTrue(events.indexOf("saveServerUrl") < events.indexOf("syncConfirmed"))
        assertTrue(events.indexOf("saveToken") < events.indexOf("syncConfirmed"))
        assertTrue(events.indexOf("saveIdentity") < events.indexOf("syncConfirmed"))
    }

    @Test
    fun bindDoesNotSendOldSessionTokenAndClearsStaleLocalAccountCache() = runTest {
        val events = mutableListOf<String>()
        val dao = FakeExpenseDao(events)
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
        val settingsStore = FakeTicketboxSettingsStore(events).apply {
            saveAvailableLedgersJson("""[{"ledger_id":"old","name":"Old","role":"owner"}]""")
        }
        val tokenStore = FakeSessionTokenStore(events).apply { saveToken("old-session-token") }
        val apiService = FakeApiService(events, confirmedFailuresRemaining = 1)
        val apiFactory = FakeApiServiceFactory(apiService)
        val repository = ExpenseRepository(
            expenseDao = dao,
            apiClient = apiFactory,
            settingsStore = settingsStore,
            tokenStore = tokenStore,
            deviceNameProvider = { "Android Test Device" },
        )

        val result = repository.bindServer("https://new.example.com", "123456").getOrThrow()

        assertTrue(result.confirmedRestoreFailed)
        assertNull(apiFactory.tokenValues.first())
        assertEquals("session-token", apiFactory.tokenValues.last())
        assertTrue(dao.getConfirmed("owner").isEmpty())
        assertTrue(dao.getConfirmed("family").isEmpty())
        assertNull(settingsStore.availableLedgersJson())
        assertTrue(events.indexOf("clear") < events.indexOf("saveIdentity"))
    }

    @Test
    fun bindRestoreDoesNotWriteOldLedgerRowsAfterLocalLedgerChanges() = runTest {
        val events = mutableListOf<String>()
        val dao = FakeExpenseDao(events)
        val settingsStore = FakeTicketboxSettingsStore(events)
        val tokenStore = FakeSessionTokenStore(events)
        val apiService = FakeApiService(events, confirmedFailuresRemaining = 0)
        var redirected = false
        settingsStore.onSaveIdentity = {
            if (!redirected && settingsStore.activeLedgerId() == "owner") {
                redirected = true
                tokenStore.saveToken("session-family")
                settingsStore.saveIdentity(
                    accountName = "家人",
                    ledgerId = "family",
                    ledgerName = "家庭账本",
                    deviceName = "Pixel",
                    role = "member",
                    boundAt = "2026-05-01T00:05:00Z",
                )
            }
        }
        val repository = ExpenseRepository(
            expenseDao = dao,
            apiClient = FakeApiServiceFactory(apiService),
            settingsStore = settingsStore,
            tokenStore = tokenStore,
            deviceNameProvider = { "Android Test Device" },
        )

        val result = repository.bindServer("https://api.example.com", "123456").getOrThrow()

        assertTrue(!result.confirmedRestoreFailed)
        assertEquals("family", settingsStore.activeLedgerId())
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
        val tokenStore = FakeSessionTokenStore(events)
        val apiService = FakeApiService(events, confirmedFailuresRemaining = 1)
        val apiFactory = FakeApiServiceFactory(apiService)
        val repository = ExpenseRepository(
            expenseDao = dao,
            apiClient = apiFactory,
            settingsStore = settingsStore,
            tokenStore = tokenStore,
            deviceNameProvider = { "Android Test Device" },
        )

        val bindResult = repository.bindServer("https://api.example.com", "123456").getOrThrow()
        val syncResult = repository.syncConfirmed().getOrThrow()

        assertTrue(bindResult.confirmedRestoreFailed)
        assertEquals(1, syncResult.size)
        assertEquals("高德", dao.getConfirmed("owner").single().merchant)
        assertEquals("session-token", apiFactory.tokenValues.last())
    }
}
