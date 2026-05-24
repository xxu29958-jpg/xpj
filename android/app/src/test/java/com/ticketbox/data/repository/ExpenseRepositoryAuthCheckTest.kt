package com.ticketbox.data.repository

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.ViewModelStore
import com.ticketbox.data.remote.dto.AuthCheckDto
import com.ticketbox.data.remote.dto.ServerSettingsDto
import com.ticketbox.viewmodel.SettingsViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class ExpenseRepositoryAuthCheckTest {
    @Test
    fun authCheckRefreshesStoredIdentityAndRole() = runTest {
        val settingsStore = FakeTicketboxSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveIdentity(
                accountName = "我",
                ledgerId = "owner",
                ledgerName = "我的小票夹",
                deviceName = "Pixel",
                role = "member",
                boundAt = "2026-05-01T00:00:00Z",
            )
        }
        val tokenStore = FakeSessionTokenStore().apply { saveToken("session-token") }
        val apiService = FakeApiService(
            events = mutableListOf(),
            confirmedFailuresRemaining = 0,
            checkAuthResult = AuthCheckDto(
                status = "ok",
                accountName = "我",
                ledgerId = "family",
                ledgerName = "家庭账本",
                deviceName = "Pixel",
                role = "viewer",
                scope = "app",
            ),
        )
        val repository = ExpenseRepository(
            expenseDao = FakeExpenseDao(),
            apiClient = FakeApiServiceFactory(apiService),
            settingsStore = settingsStore,
            tokenStore = tokenStore,
            deviceNameProvider = { "Android Test Device" },
        )

        repository.testConnection().getOrThrow()

        assertEquals("family", settingsStore.activeLedgerId())
        assertEquals("家庭账本", settingsStore.ledgerName())
        assertEquals("viewer", settingsStore.role())
        assertTrue(!repository.canModifyLedger())
    }

    @Test
    fun authCheckSlowResponseDoesNotOverwriteNewActiveLedger() = runTest {
        val settingsStore = FakeTicketboxSettingsStore().apply {
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
        val tokenStore = FakeSessionTokenStore().apply { saveToken("session-a") }
        val apiService = FakeApiService(
            events = mutableListOf(),
            confirmedFailuresRemaining = 0,
            checkAuthResult = AuthCheckDto(
                status = "ok",
                accountName = "我",
                ledgerId = "owner",
                ledgerName = "我的小票夹",
                deviceName = "Pixel",
                role = "owner",
                scope = "app",
            ),
        )
        apiService.onCheckAuth = {
            tokenStore.saveToken("session-b")
            settingsStore.saveIdentity(
                accountName = "我",
                ledgerId = "family",
                ledgerName = "家庭账本",
                deviceName = "Pixel",
                role = "member",
                boundAt = "2026-05-01T00:05:00Z",
            )
        }
        val repository = ExpenseRepository(
            expenseDao = FakeExpenseDao(),
            apiClient = FakeApiServiceFactory(apiService),
            settingsStore = settingsStore,
            tokenStore = tokenStore,
            deviceNameProvider = { "Android Test Device" },
        )

        repository.testConnection().getOrThrow()

        assertEquals("family", settingsStore.activeLedgerId())
        assertEquals("家庭账本", settingsStore.ledgerName())
        assertEquals("member", settingsStore.role())
        assertEquals("session-b", tokenStore.getToken())
    }

    @Test
    fun authCheckLedgerCorrectionClearsTargetCacheBeforeIdentitySwitch() = runTest {
        val events = mutableListOf<String>()
        val dao = FakeExpenseDao(events).apply {
            insert(
                cachedConfirmedEntity(
                    serverId = 8,
                    publicId = "target-stale",
                    merchant = "旧家庭",
                    ledgerId = "family",
                ),
            )
            insert(
                cachedConfirmedEntity(
                    serverId = 9,
                    publicId = "current-cache",
                    merchant = "当前账本",
                    ledgerId = "owner",
                ),
            )
        }
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
        val tokenStore = FakeSessionTokenStore().apply { saveToken("session-token") }
        val apiService = FakeApiService(
            events = events,
            confirmedFailuresRemaining = 0,
            checkAuthResult = AuthCheckDto(
                status = "ok",
                accountName = "我",
                ledgerId = "family",
                ledgerName = "家庭账本",
                deviceName = "Pixel",
                role = "member",
                scope = "app",
            ),
        )
        val repository = ExpenseRepository(
            expenseDao = dao,
            apiClient = FakeApiServiceFactory(apiService),
            settingsStore = settingsStore,
            tokenStore = tokenStore,
            deviceNameProvider = { "Android Test Device" },
        )

        repository.testConnection().getOrThrow()

        assertEquals("family", settingsStore.activeLedgerId())
        assertTrue(dao.getConfirmed("family").isEmpty())
        assertEquals(listOf(9L), dao.getConfirmed("owner").map { it.serverId })
        assertTrue(events.indexOf("clearForLedger:family") < events.lastIndexOf("saveIdentity"))
        assertTrue(
            events.indexOf("clearLastConfirmedSyncAtForLedger:family") < events.lastIndexOf("saveIdentity"),
        )
    }

    @Test
    fun settingsRefreshesIdentityChangedByInvitationAccept() = runTest {
        val dispatcher = StandardTestDispatcher(testScheduler)
        Dispatchers.setMain(dispatcher)
        val viewModelStore = ViewModelStore()
        try {
            val settingsStore = FakeTicketboxSettingsStore().apply {
                saveServerUrl("https://api.example.com")
                saveIdentity(
                    accountName = "我",
                    ledgerId = "old",
                    ledgerName = "旧账本",
                    deviceName = "旧设备",
                    role = "owner",
                    boundAt = "2026-05-01T00:00:00Z",
                )
            }
            val tokenStore = FakeSessionTokenStore().apply { saveToken("session-token") }
            val apiClient = FakeApiServiceFactory(
                FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0),
            )
            val repository = ExpenseRepository(
                expenseDao = FakeExpenseDao(),
                apiClient = apiClient,
                settingsStore = settingsStore,
                tokenStore = tokenStore,
                deviceNameProvider = { "Android Test Device" },
            )
            val ruleRepository = RuleRepository(
                apiClient = apiClient,
                settingsStore = settingsStore,
                tokenStore = tokenStore,
            )
            val merchantRepository = MerchantRepository(
                apiClient = apiClient,
                settingsStore = settingsStore,
                tokenStore = tokenStore,
            )
            val viewModel = ViewModelProvider(
                viewModelStore,
                object : ViewModelProvider.Factory {
                    @Suppress("UNCHECKED_CAST")
                    override fun <T : ViewModel> create(modelClass: Class<T>): T {
                        return SettingsViewModel(
                            repository,
                            ruleRepository,
                            merchantRepository,
                            settingsStore,
                        ) as T
                    }
                },
            )[SettingsViewModel::class.java]

            settingsStore.saveIdentity(
                accountName = "2468",
                ledgerId = "family",
                ledgerName = "家庭账本",
                deviceName = "9753",
                role = "viewer",
                boundAt = "2026-05-13T00:00:00Z",
            )

            viewModel.refreshLocalBindingState()

            val state = viewModel.uiState.value
            assertEquals("2468", state.accountName)
            assertEquals("家庭账本", state.ledgerName)
            assertEquals("9753", state.deviceName)
            assertEquals("viewer", state.role)
        } finally {
            viewModelStore.clear()
            advanceUntilIdle()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun serverSettingsDoesNotPersistMismatchedLedgerSnapshot() = runTest {
        val settingsStore = FakeTicketboxSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveIdentity(
                accountName = "我",
                ledgerId = "family",
                ledgerName = "家庭账本",
                deviceName = "Pixel",
                role = "viewer",
                boundAt = "2026-05-01T00:00:00Z",
            )
        }
        val tokenStore = FakeSessionTokenStore().apply { saveToken("session-token") }
        val apiService = FakeApiService(
            events = mutableListOf(),
            confirmedFailuresRemaining = 0,
            serverSettingsResult = ServerSettingsDto(
                accountName = "我",
                ledgerId = "owner",
                ledgerName = "我的小票夹",
                ledgerIsDefault = true,
                deviceName = "Pixel",
                role = "owner",
                status = "ok",
                storageStatus = "normal",
                pendingCount = 0,
                confirmedCount = 0,
                rejectedCount = 0,
                suspectedDuplicateCount = 0,
                uploadStorageBytes = 0,
                latestUploadAt = null,
            ),
        )
        val repository = ExpenseRepository(
            expenseDao = FakeExpenseDao(),
            apiClient = FakeApiServiceFactory(apiService),
            settingsStore = settingsStore,
            tokenStore = tokenStore,
            deviceNameProvider = { "Android Test Device" },
        )

        val settings = repository.serverSettings().getOrThrow()

        assertEquals("owner", settings.ledgerId)
        assertEquals("family", settingsStore.activeLedgerId())
        assertEquals("家庭账本", settingsStore.ledgerName())
        assertEquals("viewer", settingsStore.role())
    }
}
