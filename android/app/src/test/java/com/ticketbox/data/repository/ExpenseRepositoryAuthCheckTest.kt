package com.ticketbox.data.repository

import com.ticketbox.data.local.PersistedLedgerIdentity

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
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class ExpenseRepositoryAuthCheckTest {
    @Test
    fun legacySessionHydratesStableIdentityBeforeNormalRequests() = runTest {
        val settingsStore = boundSettingsStore()
        val tokenStore = TestSessionFixture().apply {
            saveToken("legacy-session-token")
            val current = requireNotNull(sessionStore.currentSession())
            sessionStore.replaceForFixture(
                current.copy(
                    serverId = null,
                    dataGeneration = null,
                    identity = current.identity.copy(
                        accountPublicId = null,
                        devicePublicId = null,
                    ),
                ),
            )
        }
        val repository = ExpenseRepository(
            expenseDao = FakeExpenseDao(),
            binding = testServerSessionBinding(
                apiClient = FakeApiServiceFactory(
                    FakeApiService(
                        events = mutableListOf(),
                        confirmedFailuresRemaining = 0,
                        checkAuthResult = AuthCheckDto(
                            status = "ok",
                            serverId = TEST_SERVER_ID,
                            dataGeneration = TEST_DATA_GENERATION,
                            accountPublicId = TEST_ACCOUNT_PUBLIC_ID,
                            devicePublicId = TEST_DEVICE_PUBLIC_ID,
                            accountName = "我",
                            ledgerId = "owner",
                            ledgerName = "我的小票夹",
                            deviceName = "Pixel",
                            role = "owner",
                            scope = "app",
                        ),
                    ),
                ),
                settingsStore = settingsStore,
                tokenStore = tokenStore,
            ),
        )

        assertNotNull(repository.reconcileActiveSession()).getOrThrow()

        val hydrated = requireNotNull(tokenStore.sessionStore.currentSession())
        assertEquals(TEST_SERVER_ID, hydrated.serverId)
        assertEquals(TEST_DATA_GENERATION, hydrated.dataGeneration)
        assertEquals(TEST_ACCOUNT_PUBLIC_ID, hydrated.identity.accountPublicId)
        assertEquals(TEST_DEVICE_PUBLIC_ID, hydrated.identity.devicePublicId)
        assertEquals(null, repository.reconcileActiveSession())
    }

    @Test
    fun authCheckRefreshesStoredIdentityAndRole() = runTest {
        val settingsStore = FakeTicketboxSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveIdentity(
                PersistedLedgerIdentity(
                    accountName = "我",
                    ledgerId = "owner",
                    ledgerName = "我的小票夹",
                    deviceName = "Pixel",
                    role = "member",
                    boundAt = "2026-05-01T00:00:00Z",
                )
            )
        }
        val tokenStore = TestSessionFixture().apply { saveToken("session-token") }
        val apiService = FakeApiService(
            events = mutableListOf(),
            confirmedFailuresRemaining = 0,
            checkAuthResult = AuthCheckDto(
                status = "ok",
                serverId = TEST_SERVER_ID,
                dataGeneration = TEST_DATA_GENERATION,
                accountPublicId = TEST_ACCOUNT_PUBLIC_ID,
                devicePublicId = TEST_DEVICE_PUBLIC_ID,
                accountName = "更新后的我",
                ledgerId = "owner",
                ledgerName = "更新后的个人账本",
                deviceName = "Pixel 9",
                role = "viewer",
                scope = "app",
            ),
        )
        val repository = ExpenseRepository(
            expenseDao = FakeExpenseDao(),
            binding = testServerSessionBinding(
                apiClient = FakeApiServiceFactory(apiService),
                settingsStore = settingsStore,
                tokenStore = tokenStore,
            ),
            deviceNameProvider = { "Android Test Device" },
        )

        repository.testConnection().getOrThrow()

        val binding = requireNotNull(repository.localBinding())
        assertEquals("owner", binding.ledgerId)
        assertEquals("更新后的我", binding.accountName)
        assertEquals("更新后的个人账本", binding.ledgerName)
        assertEquals("Pixel 9", binding.deviceName)
        assertEquals("viewer", binding.role)
        assertTrue(!repository.canModifyLedger())
    }

    @Test
    fun authCheckSlowResponseDoesNotOverwriteNewActiveLedger() = runTest {
        val settingsStore = FakeTicketboxSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveIdentity(
                PersistedLedgerIdentity(
                    accountName = "我",
                    ledgerId = "owner",
                    ledgerName = "我的小票夹",
                    deviceName = "Pixel",
                    role = "owner",
                    boundAt = "2026-05-01T00:00:00Z",
                )
            )
        }
        val tokenStore = TestSessionFixture().apply { saveToken("session-a") }
        val apiService = FakeApiService(
            events = mutableListOf(),
            confirmedFailuresRemaining = 0,
            checkAuthResult = AuthCheckDto(
                status = "ok",
                serverId = TEST_SERVER_ID,
                dataGeneration = TEST_DATA_GENERATION,
                accountPublicId = TEST_ACCOUNT_PUBLIC_ID,
                devicePublicId = TEST_DEVICE_PUBLIC_ID,
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
                PersistedLedgerIdentity(
                    accountName = "我",
                    ledgerId = "family",
                    ledgerName = "家庭账本",
                    deviceName = "Pixel",
                    role = "member",
                    boundAt = "2026-05-01T00:05:00Z",
                )
            )
        }
        val repository = ExpenseRepository(
            expenseDao = FakeExpenseDao(),
            binding = testServerSessionBinding(
                apiClient = FakeApiServiceFactory(apiService),
                settingsStore = settingsStore,
                tokenStore = tokenStore,
            ),
            deviceNameProvider = { "Android Test Device" },
        )

        repository.testConnection().getOrThrow()

        assertEquals("family", settingsStore.activeLedgerId())
        assertEquals("家庭账本", settingsStore.ledgerName())
        assertEquals("member", settingsStore.role())
        assertEquals("session-b", tokenStore.getToken())
    }

    @Test
    fun authCheckCannotSilentlySwitchLedgerOrClearEitherCache() = runTest {
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
        val settingsStore = boundSettingsStore(events = events)
        val tokenStore = TestSessionFixture().apply { saveToken("session-token") }
        val apiService = FakeApiService(
            events = events,
            confirmedFailuresRemaining = 0,
            checkAuthResult = AuthCheckDto(
                status = "ok",
                serverId = TEST_SERVER_ID,
                dataGeneration = TEST_DATA_GENERATION,
                accountPublicId = TEST_ACCOUNT_PUBLIC_ID,
                devicePublicId = TEST_DEVICE_PUBLIC_ID,
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
            binding = testServerSessionBinding(
                apiClient = FakeApiServiceFactory(apiService),
                settingsStore = settingsStore,
                tokenStore = tokenStore,
            ),
            deviceNameProvider = { "Android Test Device" },
        )

        val failure = repository.testConnection().exceptionOrNull()

        assertEquals(LedgerRequestGuard.LEDGER_CHANGED_MESSAGE, failure?.message)
        assertEquals("owner", repository.localBinding()?.ledgerId)
        assertEquals(listOf(8L), dao.getConfirmed("family").map { it.serverId })
        assertEquals(listOf(9L), dao.getConfirmed("owner").map { it.serverId })
        assertTrue("clearForLedger:family" !in events)
        assertTrue("clearLastConfirmedSyncAtForLedger:family" !in events)
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
                    PersistedLedgerIdentity(
                        accountName = "我",
                        ledgerId = "old",
                        ledgerName = "旧账本",
                        deviceName = "旧设备",
                        role = "owner",
                        boundAt = "2026-05-01T00:00:00Z",
                    )
                )
            }
            val tokenStore = TestSessionFixture().apply { saveToken("session-token") }
            val apiClient = FakeApiServiceFactory(
                FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0),
            )
            val repository = ExpenseRepository(
                expenseDao = FakeExpenseDao(),
                binding = testServerSessionBinding(
                    apiClient = apiClient,
                    settingsStore = settingsStore,
                    tokenStore = tokenStore,
                ),
                deviceNameProvider = { "Android Test Device" },
            )
            val viewModel = settingsViewModel(viewModelStore, repository, settingsStore)
            tokenStore.acceptInvitationForFixture(
                ledgerId = "family",
                ledgerName = "家庭账本",
                role = "viewer",
                accountName = "2468",
                deviceName = "9753",
            )

            viewModel.refreshLocalBindingState()

            val state = viewModel.uiState.value
            assertEquals("旧账本", settingsStore.ledgerName())
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
                PersistedLedgerIdentity(
                    accountName = "我",
                    ledgerId = "family",
                    ledgerName = "家庭账本",
                    deviceName = "Pixel",
                    role = "viewer",
                    boundAt = "2026-05-01T00:00:00Z",
                )
            )
        }
        val tokenStore = TestSessionFixture().apply { saveToken("session-token") }
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
            binding = testServerSessionBinding(
                apiClient = FakeApiServiceFactory(apiService),
                settingsStore = settingsStore,
                tokenStore = tokenStore,
            ),
            deviceNameProvider = { "Android Test Device" },
        )

        val settings = repository.serverSettings().getOrThrow()

        assertEquals("owner", settings.ledgerId)
        assertEquals("family", settingsStore.activeLedgerId())
        assertEquals("家庭账本", settingsStore.ledgerName())
        assertEquals("viewer", settingsStore.role())
    }
}

private fun settingsViewModel(
    store: ViewModelStore,
    repository: ExpenseRepository,
    settingsStore: FakeTicketboxSettingsStore,
): SettingsViewModel = ViewModelProvider(
    store,
    object : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T =
            SettingsViewModel(
                ExpenseRepositorySettingsActions(repository),
                settingsStore,
            ) as T
    },
)[SettingsViewModel::class.java]
