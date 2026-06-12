package com.ticketbox.viewmodel

import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.repository.BindServerResult
import com.ticketbox.data.repository.ServerBindingRepository
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.security.SessionTokenStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class AppViewModelBindingTest {
    @Test
    fun bindKeepsUserBoundWhenConfirmedRestoreFails() = runTest {
        val dispatcher = StandardTestDispatcher(testScheduler)
        Dispatchers.setMain(dispatcher)
        try {
            val viewModel = AppViewModel(
                repository = FakeBindingRepository(
                    Result.success(BindServerResult(confirmedRestoreFailed = true)),
                ),
                settingsStore = FakeAppSettingsStore(initialBound = false),
                tokenStore = FakeSessionTokenStore(initialToken = null),
            )

            viewModel.bind("https://api.example.com", "123456")
            advanceUntilIdle()

            val state = viewModel.uiState.value
            assertTrue(state.isBound)
            assertTrue(state.unlocked)
            assertEquals(false, state.binding)
            assertEquals(BIND_RESTORE_FAILED_MESSAGE, state.authMessage)
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun disabledLocalAuthBypassStartsUnlockedEvenWhenStoreRequiresUnlock() = runTest {
        val dispatcher = StandardTestDispatcher(testScheduler)
        Dispatchers.setMain(dispatcher)
        try {
            val settingsStore = FakeAppSettingsStore(initialBound = true, requiresUnlock = true)
            val viewModel = AppViewModel(
                repository = FakeBindingRepository(Result.success(BindServerResult())),
                settingsStore = settingsStore,
                tokenStore = FakeSessionTokenStore(initialToken = "tk_bound"),
                requireLocalUnlock = false,
            )

            assertTrue(viewModel.uiState.value.isBound)
            assertTrue(viewModel.uiState.value.unlocked)

            viewModel.markBackgrounded()
            viewModel.refreshUnlockRequirement()

            assertEquals(0, settingsStore.markBackgroundedCalls)
            assertTrue(viewModel.uiState.value.unlocked)
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun enabledLocalAuthKeepsBoundAppLockedWhenStoreRequiresUnlock() = runTest {
        val dispatcher = StandardTestDispatcher(testScheduler)
        Dispatchers.setMain(dispatcher)
        try {
            val viewModel = AppViewModel(
                repository = FakeBindingRepository(Result.success(BindServerResult())),
                settingsStore = FakeAppSettingsStore(initialBound = true, requiresUnlock = true),
                tokenStore = FakeSessionTokenStore(initialToken = "tk_release"),
                requireLocalUnlock = true,
            )

            assertTrue(viewModel.uiState.value.isBound)
            assertEquals(false, viewModel.uiState.value.unlocked)
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun refreshBindingStateFlipsToBoundAndUnlockedAfterOutOfBandJoin() = runTest {
        val dispatcher = StandardTestDispatcher(testScheduler)
        Dispatchers.setMain(dispatcher)
        try {
            val settingsStore = FakeAppSettingsStore(initialBound = false, requiresUnlock = true)
            val tokenStore = FakeSessionTokenStore(initialToken = null)
            val viewModel = AppViewModel(
                repository = FakeBindingRepository(Result.success(BindServerResult())),
                settingsStore = settingsStore,
                tokenStore = tokenStore,
                requireLocalUnlock = true,
            )
            assertEquals(false, viewModel.uiState.value.isBound)

            // Simulate LedgerRepository.acceptInvitation(serverUrlOverride=…)
            // having persisted a binding behind the VM's back (the cold-start
            // invitation join path).
            settingsStore.bound = true
            tokenStore.saveToken("tk_joined")
            viewModel.refreshBindingState()

            assertTrue(viewModel.uiState.value.isBound)
            // Mirrors bind(): a freshly persisted binding starts unlocked —
            // without this the new member lands on the unlock screen.
            assertTrue(viewModel.uiState.value.unlocked)
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun refreshBindingStateWithoutPersistedBindingStaysUnbound() = runTest {
        val dispatcher = StandardTestDispatcher(testScheduler)
        Dispatchers.setMain(dispatcher)
        try {
            val viewModel = AppViewModel(
                repository = FakeBindingRepository(Result.success(BindServerResult())),
                settingsStore = FakeAppSettingsStore(initialBound = false),
                tokenStore = FakeSessionTokenStore(initialToken = null),
            )

            viewModel.refreshBindingState()

            assertEquals(false, viewModel.uiState.value.isBound)
            assertEquals(false, viewModel.uiState.value.unlocked)
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun disableLocalUnlockEntersAppAndRaisesBannerFlag() = runTest {
        // Audit 8.1 branch 3: device has no biometric and no usable lock-screen
        // credential. The gate's probe calls disableLocalUnlock() — the bound app
        // must enter (unlocked) AND flag the advisory banner, with no stale error.
        val dispatcher = StandardTestDispatcher(testScheduler)
        Dispatchers.setMain(dispatcher)
        try {
            val viewModel = AppViewModel(
                repository = FakeBindingRepository(Result.success(BindServerResult())),
                settingsStore = FakeAppSettingsStore(initialBound = true, requiresUnlock = true),
                tokenStore = FakeSessionTokenStore(initialToken = "tk_release"),
                requireLocalUnlock = true,
            )
            assertEquals(false, viewModel.uiState.value.unlocked)

            viewModel.unlockFailed(BIND_RESTORE_FAILED_MESSAGE)
            viewModel.disableLocalUnlock()

            assertTrue(viewModel.uiState.value.unlocked)
            assertTrue(viewModel.uiState.value.localUnlockDisabled)
            assertEquals(null, viewModel.uiState.value.authMessage)
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun refreshUnlockRequirementStaysUnlockedOnceLocalUnlockDisabled() = runTest {
        // Degradation path: a device whose local door was gracefully disabled must
        // NOT be re-locked by a later background→resume cycle (refreshUnlockRequirement)
        // — there is no way to satisfy the door, so re-locking would re-trap the user.
        val dispatcher = StandardTestDispatcher(testScheduler)
        Dispatchers.setMain(dispatcher)
        try {
            val settingsStore = FakeAppSettingsStore(initialBound = true, requiresUnlock = true)
            val viewModel = AppViewModel(
                repository = FakeBindingRepository(Result.success(BindServerResult())),
                settingsStore = settingsStore,
                tokenStore = FakeSessionTokenStore(initialToken = "tk_release"),
                requireLocalUnlock = true,
            )

            viewModel.disableLocalUnlock()
            assertTrue(viewModel.uiState.value.unlocked)

            // Subsequent resume: store still says "requires unlock", but the disabled
            // flag short-circuits the re-lock.
            viewModel.markBackgrounded()
            viewModel.refreshUnlockRequirement()

            assertTrue(viewModel.uiState.value.unlocked)
            assertTrue(viewModel.uiState.value.localUnlockDisabled)
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun refreshUnlockRequirementReLocksWhenDoorStillActive() = runTest {
        // Counterpart pin: while the local door is NOT disabled (a real biometric /
        // credential device), a background→resume that the store says requires unlock
        // MUST re-lock — the graceful-disable short-circuit must not leak into the
        // normal secured path.
        val dispatcher = StandardTestDispatcher(testScheduler)
        Dispatchers.setMain(dispatcher)
        try {
            val viewModel = AppViewModel(
                repository = FakeBindingRepository(Result.success(BindServerResult())),
                settingsStore = FakeAppSettingsStore(initialBound = true, requiresUnlock = true),
                tokenStore = FakeSessionTokenStore(initialToken = "tk_release"),
                requireLocalUnlock = true,
            )
            viewModel.unlockSucceeded()
            assertTrue(viewModel.uiState.value.unlocked)

            viewModel.refreshUnlockRequirement()

            assertEquals(false, viewModel.uiState.value.unlocked)
            assertEquals(false, viewModel.uiState.value.localUnlockDisabled)
        } finally {
            Dispatchers.resetMain()
        }
    }
}

private class FakeBindingRepository(
    private val bindResult: Result<BindServerResult>,
) : ServerBindingRepository {
    override suspend fun bindServer(serverUrl: String, pairingCode: String): Result<BindServerResult> = bindResult

    override suspend fun clearBinding() = Unit
}

private class FakeAppSettingsStore(
    initialBound: Boolean,
    private val requiresUnlock: Boolean = false,
) : TicketboxSettingsStore {
    override val backgroundSettingsFlow: Flow<BackgroundSettings> = emptyFlow()
    var bound: Boolean = initialBound
    var markBackgroundedCalls: Int = 0
        private set

    override fun serverUrl(): String? = null

    override fun appSkinKey(): String? = null

    override fun monthlyBudgetCents(): Long? = null

    override fun saveMonthlyBudgetCents(amountCents: Long?) = Unit

    override fun lastConfirmedSyncAt(): String? = null

    override fun accountName(): String? = null

    override fun ledgerName(): String? = null

    override fun activeLedgerId(): String? = null

    override fun activeLedgerName(): String? = null

    override fun availableLedgersJson(): String? = null

    override fun observeActiveLedgerId(): Flow<String?> = emptyFlow()

    override fun saveActiveLedger(ledgerId: String, ledgerName: String) = Unit

    override fun saveAvailableLedgersJson(json: String?) = Unit

    override fun deviceName(): String? = null

    override fun role(): String? = null

    override fun boundAt(): String? = null

    override fun saveIdentity(
        accountName: String,
        ledgerId: String,
        ledgerName: String,
        deviceName: String,
        role: String,
        boundAt: String,
    ) = Unit

    override fun saveLastConfirmedSyncAt(value: String) = Unit

    override fun clearLastConfirmedSyncAt() = Unit

    override fun clearLastConfirmedSyncAtForLedger(ledgerId: String) = Unit

    override fun clearLedgerScopedRuntimeState() = Unit

    override fun lastUploadAt(): String? = null

    override fun saveLastUploadAt(value: String) = Unit

    override fun saveAppSkinKey(skinKey: String) = Unit

    override fun currencyCodeKey(): String? = null

    override fun saveCurrencyCodeKey(currencyKey: String) = Unit

    override fun observeCurrencyCodeKey(): Flow<String?> = emptyFlow()

    override fun saveServerUrl(serverUrl: String) = Unit

    override fun isBound(): Boolean = bound

    override fun markUnlocked() = Unit

    override fun markBackgrounded() {
        markBackgroundedCalls += 1
    }

    override fun requiresUnlock(): Boolean = requiresUnlock

    override fun clear() = Unit
}

private class FakeSessionTokenStore(
    initialToken: String?,
) : SessionTokenStore {
    private var token: String? = initialToken

    override fun saveToken(token: String) {
        this.token = token
    }

    override fun getToken(): String? = token

    override fun clear() {
        token = null
    }
}
