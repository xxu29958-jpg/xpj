package com.ticketbox.viewmodel

import com.ticketbox.data.local.PersistedLedgerIdentity

import com.ticketbox.R
import com.ticketbox.data.repository.SettingsActions
import com.ticketbox.data.repository.LocalBindingInfo
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.boundSettingsStore
import com.ticketbox.domain.model.ConnectionDiagnostics
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.NotificationPreferences
import com.ticketbox.domain.model.ServerSettings
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
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

    @Test
    fun roleRevocationBeforeTheNextFrameCannotKeepAutoCaptureEnabled() = runTest(dispatcher) {
        val repo = FakeSettingsActions()
        val store = boundSettingsStore()
        val vm = SettingsViewModel(repo, store)
        runCurrent()

        repo.currentLedgerRoleValue = "viewer"
        vm.saveNotificationPreferences(NotificationPreferences(autoCaptureEnabled = true, pendingDraftReminders = true))

        assertFalse(store.notificationPreferences().autoCaptureEnabled)
        assertTrue(store.notificationPreferences().pendingDraftReminders)
        assertEquals(MessageTone.Info, vm.uiState.value.messageTone)
    }

    internal class FakeSettingsActions(
        private var lastConfirmedSyncAtValue: String? = null,
        private val clearLocalCacheGate: CompletableDeferred<Unit>? = null,
        private val clearLocalCacheFailure: Throwable? = null,
    ) : SettingsActions {
        var clearLocalCacheCalls = 0
        var currentLedgerRoleValue: String? = "owner"
            set(value) { field = value; accessUpdates.value = currentAccess() }
        var diagnostics: ConnectionDiagnostics = ConnectionDiagnostics(checks = emptyList())
        var diagnosticsFailure: Throwable? = null
        var serverSettingsValue: ServerSettings? = null
        var serverSettingsFailure: Throwable? = null
        var diagnosticsGate: CompletableDeferred<Unit>? = null
        var binding = LocalBindingInfo(
            "https://api.example.com", "Account", "owner", "Ledger", "Pixel", "owner", "2026-05-01T00:00:00Z",
        )
            set(value) { field = value; accessUpdates.value = currentAccess() }
        var sessionGenerationValue = "session"
            set(value) { field = value; accessUpdates.value = currentAccess() }
        private val accessUpdates = MutableStateFlow(currentAccess())

        override fun localBinding(): LocalBindingInfo = binding.copy(role = currentLedgerRoleValue ?: "viewer")

        override fun currentAccess(): LedgerAccessContext = LedgerAccessContext(
            LogicalSessionBinding(binding.serverUrl, binding.ledgerId, "test-owner", sessionGenerationValue, "binding"),
            currentLedgerRoleValue != "viewer",
        )

        override fun observeAccess(): Flow<LedgerAccessContext?> = accessUpdates

        override fun lastConfirmedSyncAt(): String? = lastConfirmedSyncAtValue

        override fun lastUploadAt(): String? = null

        override suspend fun runConnectionDiagnostics(binding: LogicalSessionBinding): Result<ConnectionDiagnostics> {
            assertEquals(currentAccess().binding, binding)
            diagnosticsGate?.await()
            return diagnosticsFailure?.let { Result.failure(it) } ?: Result.success(diagnostics)
        }

        override suspend fun serverSettings(): Result<ServerSettings> =
            serverSettingsFailure?.let { Result.failure(it) } ?: Result.success(serverSettingsValue ?: defaultServerSettings())

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
