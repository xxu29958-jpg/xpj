package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.PaginatedExpensesDto
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class ExpenseRepositoryConfirmedSyncTest {
    @Test
    fun confirmedSyncForwardsSelectedTagFilter() = runTest {
        val events = mutableListOf<String>()
        val settingsStore = FakeTicketboxSettingsStore(events).apply {
            saveServerUrl("https://api.example.com")
            saveIdentity(
                accountName = "我",
                ledgerId = "owner",
                ledgerName = "我的小票夹",
                deviceName = "Pixel",
                role = "owner",
                boundAt = "2026-05-01T00:00:00Z",
            )
        }
        val apiService = FakeApiService(events, confirmedFailuresRemaining = 0)
        val repository = ExpenseRepository(
            expenseDao = FakeExpenseDao(),
            apiClient = FakeApiServiceFactory(apiService),
            settingsStore = settingsStore,
            tokenStore = FakeSessionTokenStore().apply { saveToken("session-token") },
            deviceNameProvider = { "Android Test Device" },
        )

        repository.syncConfirmed(month = "2026-05", category = "餐饮", tag = "AI").getOrThrow()

        assertEquals("2026-05", apiService.lastConfirmedMonth)
        assertEquals("餐饮", apiService.lastConfirmedCategory)
        assertEquals("AI", apiService.lastConfirmedTag)
    }

    @Test
    fun fullConfirmedSyncDeletesRemoteMissingCachedRows() = runTest {
        val dao = FakeExpenseDao()
        dao.insert(cachedConfirmedEntity(serverId = 9, publicId = "remote-kept", merchant = "旧高德"))
        dao.insert(cachedConfirmedEntity(serverId = 99, publicId = "remote-deleted", merchant = "已删除"))
        val settingsStore = boundSettingsStore()
        val repository = ExpenseRepository(
            expenseDao = dao,
            apiClient = FakeApiServiceFactory(FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0)),
            settingsStore = settingsStore,
            tokenStore = FakeSessionTokenStore().apply { saveToken("session-token") },
            deviceNameProvider = { "Android Test Device" },
        )

        repository.syncConfirmed().getOrThrow()

        val cached = dao.getConfirmed("owner")
        assertEquals(listOf(9L), cached.map { it.serverId })
        assertEquals("高德", cached.single().merchant)
        assertTrue(settingsStore.lastConfirmedSyncAt() != null)
    }

    @Test
    fun fullConfirmedSyncDoesNotPruneRowConfirmedDuringFetch() = runTest {
        // Audit follow-up P2: the full-list response predates anything cached
        // while the (paginated) fetch is in flight. A row confirmed mid-fetch
        // (cacheIfConfirmed) is missing from that response by timing alone —
        // it must NOT be pruned as "server-deleted". The pre-fetch snapshot
        // in syncConfirmedFromService scopes the prune to pre-existing rows.
        val dao = FakeExpenseDao()
        dao.insert(cachedConfirmedEntity(serverId = 9, publicId = "remote-kept", merchant = "旧高德"))
        val settingsStore = boundSettingsStore()
        val apiService = FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0).apply {
            onConfirmedRequest = {
                dao.insert(
                    cachedConfirmedEntity(serverId = 77, publicId = "in-flight-confirm", merchant = "新确认"),
                )
            }
        }
        val repository = ExpenseRepository(
            expenseDao = dao,
            apiClient = FakeApiServiceFactory(apiService),
            settingsStore = settingsStore,
            tokenStore = FakeSessionTokenStore().apply { saveToken("session-token") },
            deviceNameProvider = { "Android Test Device" },
        )

        repository.syncConfirmed().getOrThrow()

        // serverId=9 came back in the response (kept + updated); serverId=77
        // was cached mid-fetch and must survive the prune.
        assertEquals(setOf(9L, 77L), dao.getConfirmed("owner").map { it.serverId }.toSet())
    }

    @Test
    fun filteredConfirmedSyncDoesNotDeleteUnreturnedCachedRows() = runTest {
        val dao = FakeExpenseDao()
        dao.insert(cachedConfirmedEntity(serverId = 99, publicId = "other-filter-row", merchant = "不在当前筛选"))
        val settingsStore = boundSettingsStore()
        val repository = ExpenseRepository(
            expenseDao = dao,
            apiClient = FakeApiServiceFactory(FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0)),
            settingsStore = settingsStore,
            tokenStore = FakeSessionTokenStore().apply { saveToken("session-token") },
            deviceNameProvider = { "Android Test Device" },
        )

        repository.syncConfirmed(month = "2026-05", category = "交通", tag = null).getOrThrow()

        assertEquals(listOf(9L, 99L), dao.getConfirmed("owner").mapNotNull { it.serverId }.sorted())
        assertNull(settingsStore.lastConfirmedSyncAt())
    }

    @Test
    fun fullConfirmedSyncWritesTimestampToRequestLedgerWhenActiveLedgerChangesAfterCacheWrite() = runTest {
        val dao = FakeExpenseDao()
        val settingsStore = boundSettingsStore()
        dao.onAfterApplyConfirmedSync = {
            settingsStore.saveIdentity(
                accountName = "Account",
                ledgerId = "family",
                ledgerName = "Family Ledger",
                deviceName = "Pixel",
                role = "member",
                boundAt = "2026-05-01T00:00:00Z",
            )
        }
        val repository = ExpenseRepository(
            expenseDao = dao,
            apiClient = FakeApiServiceFactory(FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0)),
            settingsStore = settingsStore,
            tokenStore = FakeSessionTokenStore().apply { saveToken("session-token") },
            deviceNameProvider = { "Android Test Device" },
        )

        repository.syncConfirmed().getOrThrow()

        assertNull(settingsStore.lastConfirmedSyncAt())
        settingsStore.saveIdentity(
            accountName = "Account",
            ledgerId = "owner",
            ledgerName = "Owner Ledger",
            deviceName = "Pixel",
            role = "owner",
            boundAt = "2026-05-01T00:00:00Z",
        )
        assertNotNull(settingsStore.lastConfirmedSyncAt())
    }

    @Test
    fun confirmedSyncFailsOnEmptyPageBeforeReportedTotal() = runTest {
        val dao = FakeExpenseDao()
        val settingsStore = boundSettingsStore()
        val apiService = FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0).apply {
            confirmedResponses[1] = PaginatedExpensesDto(
                items = emptyList(),
                page = 1,
                pageSize = 50,
                total = 2,
            )
        }
        val repository = ExpenseRepository(
            expenseDao = dao,
            apiClient = FakeApiServiceFactory(apiService),
            settingsStore = settingsStore,
            tokenStore = FakeSessionTokenStore().apply { saveToken("session-token") },
            deviceNameProvider = { "Android Test Device" },
        )

        val failure = repository.syncConfirmed().exceptionOrNull()

        assertTrue(failure is RepositoryException)
        assertTrue(failure.message!!.contains("分页异常"))
        assertTrue(dao.getConfirmed("owner").isEmpty())
        assertNull(settingsStore.lastConfirmedSyncAt())
    }

    @Test
    fun confirmedSyncSkipsCacheWhenLedgerChangesDuringRequest() = runTest {
        val events = mutableListOf<String>()
        val dao = FakeExpenseDao()
        val settingsStore = FakeTicketboxSettingsStore(events).apply {
            saveServerUrl("https://api.zen70.cn")
            saveIdentity(
                accountName = "Account",
                ledgerId = "owner",
                ledgerName = "Owner Ledger",
                deviceName = "Pixel",
                role = "owner",
                boundAt = "2026-05-01T00:00:00Z",
            )
        }
        val apiService = FakeApiService(events, confirmedFailuresRemaining = 0).apply {
            onConfirmedRequest = {
                settingsStore.saveIdentity(
                    accountName = "Account",
                    ledgerId = "family",
                    ledgerName = "Family Ledger",
                    deviceName = "Pixel",
                    role = "member",
                    boundAt = "2026-05-01T00:00:00Z",
                )
            }
        }
        val repository = ExpenseRepository(
            expenseDao = dao,
            apiClient = FakeApiServiceFactory(apiService),
            settingsStore = settingsStore,
            tokenStore = FakeSessionTokenStore().apply { saveToken("session-token") },
            deviceNameProvider = { "Android Test Device" },
        )

        val result = repository.syncConfirmed().getOrThrow()

        assertTrue(result.isEmpty())
        assertTrue(dao.getConfirmed("owner").isEmpty())
        assertTrue(dao.getConfirmed("family").isEmpty())
        assertNull(settingsStore.lastConfirmedSyncAt())
    }
}
