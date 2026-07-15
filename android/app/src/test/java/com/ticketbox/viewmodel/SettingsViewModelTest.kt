package com.ticketbox.viewmodel

import com.ticketbox.data.local.PersistedLedgerIdentity

import com.ticketbox.R
import com.ticketbox.data.repository.SettingsActions
import com.ticketbox.data.repository.boundSettingsStore
import com.ticketbox.domain.model.ConnectionDiagnostics
import com.ticketbox.domain.model.DiagnosticCheck
import com.ticketbox.domain.model.DiagnosticCheckKind
import com.ticketbox.domain.model.DiagnosticStatus
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.NotificationPreferences
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

    @Test
    fun testConnectionUsesSuccessAndDangerTones() = runTest(dispatcher) {
        val successVm = SettingsViewModel(repository = FakeSettingsActions(), settingsStore = boundSettingsStore())
        runCurrent()

        successVm.testConnection()
        runCurrent()

        val successState = successVm.uiState.value
        assertFalse(successState.busy)
        assertEquals(UiText.res(R.string.settings_vm_connection_ok), successState.message)
        assertEquals(MessageTone.Success, successState.messageTone)

        val failureVm = SettingsViewModel(
            repository = FakeSettingsActions().apply {
                testConnectionFailure = RuntimeException()
            },
            settingsStore = boundSettingsStore(),
        )
        runCurrent()

        failureVm.testConnection()
        runCurrent()

        val failureState = failureVm.uiState.value
        assertFalse(failureState.busy)
        assertEquals(UiText.res(R.string.settings_vm_connection_failed), failureState.message)
        assertEquals(MessageTone.Danger, failureState.messageTone)
    }

    @Test
    fun runDiagnosticsShowsDangerToneWithFailedChecks() = runTest(dispatcher) {
        val diagnostics = ConnectionDiagnostics(
            checks = listOf(
                DiagnosticCheck(
                    kind = DiagnosticCheckKind.Auth,
                    status = DiagnosticStatus.Fail,
                    detail = "401",
                    elapsedMs = 12L,
                ),
            ),
        )
        val repo = FakeSettingsActions().apply {
            this.diagnostics = diagnostics
        }
        val vm = SettingsViewModel(repository = repo, settingsStore = boundSettingsStore())
        runCurrent()

        vm.runDiagnostics()
        runCurrent()

        val state = vm.uiState.value
        assertFalse(state.busy)
        assertEquals(diagnostics, state.diagnostics)
        assertEquals(UiText.res(R.string.settings_vm_diagnostics_failed_count, 1), state.message)
        assertEquals(MessageTone.Danger, state.messageTone)
    }

    @Test
    fun saveNotificationPreferencesPersistsAndShowsSuccessTone() = runTest(dispatcher) {
        val store = settingsStore()
        val vm = SettingsViewModel(repository = FakeSettingsActions(), settingsStore = store)
        runCurrent()
        val preferences = NotificationPreferences(
            autoCaptureEnabled = true,
            pendingDraftReminders = true,
        )

        vm.saveNotificationPreferences(preferences)

        val state = vm.uiState.value
        assertEquals(preferences, state.notificationPreferences)
        assertEquals(preferences, store.notificationPreferences())
        assertEquals(UiText.res(R.string.settings_vm_notifications_saved), state.message)
        assertEquals(MessageTone.Success, state.messageTone)
    }

    @Test
    fun saveNotificationPreferencesForViewerDisablesAutoCaptureAndShowsInfoTone() = runTest(dispatcher) {
        val store = settingsStore(role = "viewer")
        val repo = FakeSettingsActions().apply {
            currentLedgerRoleValue = "viewer"
            serverSettingsValue = defaultServerSettings(role = "viewer")
        }
        val vm = SettingsViewModel(repository = repo, settingsStore = store)
        runCurrent()
        val requested = NotificationPreferences(
            autoCaptureEnabled = true,
            pendingDraftReminders = true,
        )
        val expected = requested.copy(autoCaptureEnabled = false)

        vm.saveNotificationPreferences(requested)

        val state = vm.uiState.value
        assertEquals(expected, state.notificationPreferences)
        assertEquals(expected, store.notificationPreferences())
        assertEquals(UiText.res(R.string.common_readonly_ledger), state.message)
        assertEquals(MessageTone.Info, state.messageTone)
    }

    private class FakeSettingsActions(
        private var lastConfirmedSyncAtValue: String? = null,
        private val clearLocalCacheGate: CompletableDeferred<Unit>? = null,
        private val clearLocalCacheFailure: Throwable? = null,
    ) : SettingsActions {
        var clearLocalCacheCalls = 0
        var currentLedgerRoleValue: String? = "owner"
        var testConnectionFailure: Throwable? = null
        var diagnostics: ConnectionDiagnostics = ConnectionDiagnostics(checks = emptyList())
        var diagnosticsFailure: Throwable? = null
        var serverSettingsValue: ServerSettings? = null

        override fun localBinding(): com.ticketbox.data.repository.LocalBindingInfo? = null

        override fun currentLedgerRole(): String? = currentLedgerRoleValue

        override fun lastConfirmedSyncAt(): String? = lastConfirmedSyncAtValue

        override fun lastUploadAt(): String? = null

        override fun monthlyBudgetCents(): Long? = null

        override fun saveMonthlyBudgetCents(amountCents: Long?) = Unit

        override suspend fun testConnection(): Result<Unit> =
            testConnectionFailure?.let { Result.failure(it) } ?: Result.success(Unit)

        override suspend fun runConnectionDiagnostics(): Result<ConnectionDiagnostics> =
            diagnosticsFailure?.let { Result.failure(it) } ?: Result.success(diagnostics)

        override suspend fun serverSettings(): Result<ServerSettings> =
            Result.success(serverSettingsValue ?: defaultServerSettings())

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
        fun settingsStore(role: String = "owner") = boundSettingsStore().apply {
            saveIdentity(
                PersistedLedgerIdentity(
                    accountName = "Account",
                    ledgerId = "owner",
                    ledgerName = "Ledger",
                    deviceName = "Pixel",
                    role = role,
                    boundAt = "2026-05-01T00:00:00Z",
                )
            )
        }

        fun defaultServerSettings(role: String = "owner"): ServerSettings = ServerSettings(
            accountName = "Account",
            ledgerId = "owner",
            ledgerName = "Ledger",
            ledgerIsDefault = true,
            deviceName = "Pixel",
            role = role,
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
