package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.SettingsActions
import com.ticketbox.data.repository.boundSettingsStore
import com.ticketbox.domain.model.ConnectionDiagnostics
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.ServerSettings
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class SettingsViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    @BeforeTest
    fun setup() {
        Dispatchers.setMain(dispatcher)
    }

    @AfterTest
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun clearLocalCacheSuccessClearsTimestampAndShowsSuccess() = runTest(dispatcher) {
        val repo = FakeSettingsActions(lastConfirmedSyncAtValue = "2026-07-05T00:00:00Z")
        val vm = SettingsViewModel(repository = repo, settingsStore = boundSettingsStore())
        runCurrent()

        vm.clearLocalCache()
        runCurrent()

        val state = vm.uiState.value
        assertEquals(1, repo.clearLocalCacheCalls)
        assertFalse(state.busy)
        assertEquals(null, state.lastConfirmedSyncAt)
        assertEquals(UiText.res(R.string.settings_vm_cache_cleared), state.message)
        assertEquals(MessageTone.Success, state.messageTone)
    }

    @Test
    fun clearLocalCacheFailureClearsBusyAndShowsDanger() = runTest(dispatcher) {
        val repo = FakeSettingsActions(clearLocalCacheFailure = RuntimeException())
        val vm = SettingsViewModel(repository = repo, settingsStore = boundSettingsStore())
        runCurrent()

        vm.clearLocalCache()
        runCurrent()

        val state = vm.uiState.value
        assertEquals(1, repo.clearLocalCacheCalls)
        assertFalse(state.busy)
        assertEquals(UiText.res(R.string.settings_vm_cache_clear_failed), state.message)
        assertEquals(MessageTone.Danger, state.messageTone)
    }

    @Test
    fun clearLocalCacheWhileBusyIsIgnored() = runTest(dispatcher) {
        val gate = CompletableDeferred<Unit>()
        val repo = FakeSettingsActions(clearLocalCacheGate = gate)
        val vm = SettingsViewModel(repository = repo, settingsStore = boundSettingsStore())
        runCurrent()

        vm.clearLocalCache()
        runCurrent()
        assertTrue(vm.uiState.value.busy)

        vm.clearLocalCache()
        runCurrent()
        assertEquals(1, repo.clearLocalCacheCalls)

        gate.complete(Unit)
        runCurrent()
        assertFalse(vm.uiState.value.busy)
    }

    private class FakeSettingsActions(
        private var lastConfirmedSyncAtValue: String? = null,
        private val clearLocalCacheGate: CompletableDeferred<Unit>? = null,
        private val clearLocalCacheFailure: Throwable? = null,
    ) : SettingsActions {
        var clearLocalCacheCalls = 0

        override fun currentLedgerRole(): String? = "owner"

        override fun lastConfirmedSyncAt(): String? = lastConfirmedSyncAtValue

        override fun lastUploadAt(): String? = null

        override fun monthlyBudgetCents(): Long? = null

        override fun saveMonthlyBudgetCents(amountCents: Long?) = Unit

        override suspend fun testConnection(): Result<Unit> = Result.success(Unit)

        override suspend fun runConnectionDiagnostics(): Result<ConnectionDiagnostics> =
            Result.success(ConnectionDiagnostics(checks = emptyList()))

        override suspend fun serverSettings(): Result<ServerSettings> =
            Result.success(defaultServerSettings())

        override suspend fun syncConfirmed(
            month: String?,
            category: String?,
            tag: String?,
        ): Result<List<Expense>> = Result.success(emptyList())

        override suspend fun clearLocalCache() {
            clearLocalCacheCalls += 1
            clearLocalCacheGate?.await()
            clearLocalCacheFailure?.let { throw it }
            lastConfirmedSyncAtValue = null
        }
    }

    private companion object {
        fun defaultServerSettings(): ServerSettings = ServerSettings(
            accountName = "Account",
            ledgerId = "owner",
            ledgerName = "Ledger",
            ledgerIsDefault = true,
            deviceName = "Pixel",
            role = "owner",
            status = "ok",
            storageStatus = "ok",
            pendingCount = 0,
            confirmedCount = 0,
            rejectedCount = 0,
            suspectedDuplicateCount = 0,
            uploadStorageBytes = 0L,
            latestUploadAt = null,
        )
    }
}
