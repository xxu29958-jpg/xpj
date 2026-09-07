package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.boundSettingsStore
import com.ticketbox.domain.model.ConnectionDiagnostics
import com.ticketbox.domain.model.DiagnosticCheck
import com.ticketbox.domain.model.DiagnosticCheckKind
import com.ticketbox.domain.model.DiagnosticStatus
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.viewmodel.SettingsViewModelTest.FakeSettingsActions
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
class SettingsConnectionViewModelTest {
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
    fun runDiagnosticsUsesSuccessAndDangerTones() = runTest(dispatcher) {
        val successVm = SettingsViewModel(repository = FakeSettingsActions(), settingsStore = boundSettingsStore())
        runCurrent()

        successVm.runDiagnostics()
        runCurrent()

        val successState = successVm.uiState.value
        assertFalse(successState.busy)
        assertEquals(UiText.res(R.string.settings_vm_diagnostics_passed), successState.message)
        assertEquals(MessageTone.Success, successState.messageTone)

        val failureVm = SettingsViewModel(
            repository = FakeSettingsActions().apply {
                diagnosticsFailure = RuntimeException()
            },
            settingsStore = boundSettingsStore(),
        )
        runCurrent()

        failureVm.runDiagnostics()
        runCurrent()

        val failureState = failureVm.uiState.value
        assertFalse(failureState.busy)
        assertEquals(UiText.res(R.string.settings_vm_diagnostics_incomplete), failureState.message)
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
        assertFalse(state.serverSettingsFresh)
    }

    @Test
    fun changingServerWithTheSameLedgerIdClearsThePreviousDiagnosis() = runTest(dispatcher) {
        val repo = FakeSettingsActions()
        val vm = SettingsViewModel(repo, boundSettingsStore())
        runCurrent()
        vm.runDiagnostics()
        runCurrent()
        assertEquals(repo.diagnostics, vm.uiState.value.diagnostics)

        repo.binding = repo.binding.copy(serverUrl = "https://other.example.com", ledgerName = "Other ledger")
        vm.refreshLocalBindingState()

        assertEquals(null, vm.uiState.value.diagnostics)
        assertFalse(vm.uiState.value.serverSettingsFresh)
        assertEquals("Other ledger", vm.uiState.value.ledgerName)
    }

    @Test
    fun lateDiagnosticSuccessCannotDescribeTheReplacementBinding() = runTest(dispatcher) {
        val gate = CompletableDeferred<Unit>()
        val repo = FakeSettingsActions().apply { diagnosticsGate = gate }
        val vm = SettingsViewModel(repo, boundSettingsStore())
        runCurrent()
        vm.runDiagnostics()
        runCurrent()
        assertTrue(vm.uiState.value.busy)

        repo.binding = repo.binding.copy(serverUrl = "https://other.example.com")
        vm.refreshLocalBindingState()
        gate.complete(Unit)
        runCurrent()

        assertEquals(null, vm.uiState.value.diagnostics)
        assertEquals(null, vm.uiState.value.message)
        assertFalse(vm.uiState.value.busy)
    }

    @Test
    fun replacingTheSessionAtTheSameAddressClearsResultsWithoutAnExplicitRefresh() = runTest(dispatcher) {
        val repo = FakeSettingsActions()
        val vm = SettingsViewModel(repo, boundSettingsStore())
        runCurrent()
        vm.runDiagnostics()
        runCurrent()

        repo.sessionGenerationValue = "replacement-session"
        runCurrent()

        assertEquals(null, vm.uiState.value.diagnostics)
        assertFalse(vm.uiState.value.serverSettingsFresh)
        assertEquals(null, vm.uiState.value.message)
    }

    @Test
    fun leavingTheConnectionPageCancelsItsPendingCheckAndAllowsAnotherAttempt() = runTest(dispatcher) {
        val repo = FakeSettingsActions().apply { diagnosticsGate = CompletableDeferred() }
        val vm = SettingsViewModel(repo, boundSettingsStore())
        runCurrent()
        vm.runDiagnostics()
        runCurrent()

        vm.cancelConnectionWork()
        runCurrent()
        assertFalse(vm.uiState.value.busy)
        assertEquals(null, vm.uiState.value.diagnostics)

        repo.diagnosticsGate = null
        vm.runDiagnostics()
        runCurrent()
        assertEquals(repo.diagnostics, vm.uiState.value.diagnostics)
        assertFalse(vm.uiState.value.busy)
    }

    @Test
    fun completedSyncWithAnUnavailableStatusRemainsAReadablePartialResult() = runTest(dispatcher) {
        val repo = FakeSettingsActions()
        val vm = SettingsViewModel(repo, boundSettingsStore())
        runCurrent()
        repo.serverSettingsFailure = RuntimeException()

        vm.sync()
        runCurrent()

        assertEquals(UiText.res(R.string.settings_vm_sync_state_unavailable), vm.uiState.value.message)
        assertEquals(MessageTone.Info, vm.uiState.value.messageTone)
        assertFalse(vm.uiState.value.serverSettingsFresh)
        assertFalse(vm.uiState.value.busy)
    }
}
