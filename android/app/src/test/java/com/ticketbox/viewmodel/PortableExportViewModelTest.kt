package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.PortableExportActions
import com.ticketbox.data.repository.PortableExportSelection
import com.ticketbox.domain.model.LedgerSummary
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.OutputStream
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.job
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class PortableExportViewModelTest {
    private val dispatcher = StandardTestDispatcher()
    private val models = mutableListOf<PortableExportViewModel>()
    @BeforeTest fun setup() { Dispatchers.setMain(dispatcher) }
    @AfterTest fun close() = runTest(dispatcher) {
        try {
            models.forEach { it.viewModelScope.coroutineContext.job.cancelAndJoin() }
        } finally {
            Dispatchers.resetMain()
        }
    }
    private fun model(exports: ExportActions) = PortableExportViewModel(exports).also { models += it }

    @Test fun chosenLedgerIsFrozenUntilTheSystemPickerReturnsAndSavedMeansComplete() = runTest(dispatcher) {
        val exports = ExportActions()
        val vm = model(exports)
        advanceUntilIdle(); vm.select("archive")
        assertTrue(vm.chooseLocation())
        vm.select("active")
        assertFalse(vm.chooseLocation())
        val document = ExportDocument()
        vm.save(document); advanceUntilIdle()
        vm.state.first { it.stage == PortableExportStage.Idle }
        assertEquals("archive", exports.requests.single().ledgerId)
        assertEquals(4, document.bytes.size())
        assertTrue(document.closed)
        assertTrue(document.completed)
        assertEquals(0, document.discards)
        assertEquals(UiText.res(R.string.portable_export_saved), vm.state.value.message)
        assertEquals(MessageTone.Success, vm.state.value.tone)
    }

    @Test fun cancellationRemovesOnlyTheNewPartialDocumentAndAllowsACompleteRetry() = runTest(dispatcher) {
        val exports = ExportActions().apply { gate = CompletableDeferred() }
        val vm = model(exports)
        advanceUntilIdle(); assertTrue(vm.chooseLocation())
        val partial = ExportDocument()
        vm.save(partial); runCurrent()
        vm.state.first { it.bytesWritten == 2L }
        assertEquals(PortableExportStage.Downloading, vm.state.value.stage)
        vm.cancel(); runCurrent()
        vm.state.first { it.stage == PortableExportStage.Idle }
        assertTrue(partial.closed)
        assertEquals(1, partial.discards)
        assertEquals(UiText.res(R.string.portable_export_cancelled), vm.state.value.message)
        exports.gate = null
        assertTrue(vm.chooseLocation())
        val complete = ExportDocument()
        vm.save(complete); advanceUntilIdle()
        vm.state.first { it.stage == PortableExportStage.Idle }
        assertEquals(0, complete.discards)
        assertEquals(UiText.res(R.string.portable_export_saved), vm.state.value.message)
    }

    @Test fun identityChangeWhilePickerIsOpenCannotExportUnderTheReplacementIdentity() = runTest(dispatcher) {
        val exports = ExportActions()
        val vm = model(exports)
        advanceUntilIdle(); assertTrue(vm.chooseLocation())
        exports.binding.value = exports.binding.value!!.copy(sessionGeneration = "new-account")
        advanceUntilIdle()
        val document = ExportDocument()
        vm.save(document); runCurrent()
        vm.state.first { document.discards == 1 && it.message != null }
        assertTrue(exports.requests.isEmpty())
        assertFalse(document.opened)
        assertEquals(1, document.discards)
        assertEquals(UiText.res(R.string.portable_export_cancelled), vm.state.value.message)
    }

    @Test fun interruptedDownloadCannotReplaceTheNewIdentityStateWithOldSuccess() = runTest(dispatcher) {
        val exports = ExportActions().apply { gate = CompletableDeferred() }
        val vm = model(exports)
        advanceUntilIdle(); assertTrue(vm.chooseLocation())
        val document = ExportDocument()
        vm.save(document); runCurrent()
        vm.state.first { it.bytesWritten == 2L }
        exports.binding.value = exports.binding.value!!.copy(sessionGeneration = "replacement")
        advanceUntilIdle()
        document.discarded.await()
        assertTrue(document.closed)
        assertEquals(PortableExportStage.Idle, vm.state.value.stage)
        assertNull(vm.state.value.message)
        assertEquals("replacement", vm.state.value.binding?.sessionGeneration)
    }

    @Test fun unwritableDestinationCannotReportSuccessAndExplainsUnremovablePartialFile() = runTest(dispatcher) {
        val exports = ExportActions().apply { failure = IOException("disk full") }
        val vm = model(exports)
        advanceUntilIdle(); assertTrue(vm.chooseLocation())
        val document = ExportDocument().apply { canDiscard = false }
        vm.save(document); runCurrent()
        vm.state.first { it.stage == PortableExportStage.Idle }
        assertEquals(1, document.discards)
        assertEquals(UiText.res(R.string.portable_export_partial), vm.state.value.message)
        assertEquals(MessageTone.Danger, vm.state.value.tone)
    }

    @Test fun failingToRecordCompletionCannotLeaveASuccessThatRestartWouldDelete() = runTest(dispatcher) {
        val vm = model(ExportActions())
        advanceUntilIdle(); assertTrue(vm.chooseLocation())
        val document = ExportDocument().apply { canComplete = false }
        vm.save(document); runCurrent()
        vm.state.first { it.stage == PortableExportStage.Idle }
        assertTrue(document.closed)
        assertEquals(1, document.discards)
        assertEquals(UiText.res(R.string.portable_export_failed), vm.state.value.message)
        assertEquals(MessageTone.Danger, vm.state.value.tone)
    }
}

private class ExportActions : PortableExportActions {
    val binding = MutableStateFlow<LogicalSessionBinding?>(LogicalSessionBinding("https://example.test", "active", "owner", "session", "binding"))
    val requests = mutableListOf<PortableExportSelection>()
    var gate: CompletableDeferred<Unit>? = null
    var failure: Throwable? = null
    override fun currentBinding() = binding.value
    override fun observeBinding() = binding
    override suspend fun ledgers(binding: LogicalSessionBinding) = Result.success(listOf(
        LedgerSummary("active", "当前账本", "viewer", true),
        LedgerSummary("archive", "归档账本", "owner", false, archivedAt = "2026-09-28T00:00:00Z"),
    ))
    override suspend fun download(selection: PortableExportSelection, open: () -> OutputStream,
        progress: (Long) -> Unit): Result<Long> {
        requests += selection
        failure?.let { return Result.failure(it) }
        open().use { output ->
            output.write(byteArrayOf(1, 2)); progress(2)
            gate?.await()
            output.write(byteArrayOf(3, 4)); progress(4)
        }
        return Result.success(4L)
    }
}

private class ExportDocument : PortableExportDestination {
    val bytes = ByteArrayOutputStream()
    val discarded = CompletableDeferred<Unit>()
    var opened = false
    var closed = false
    var discards = 0
    var canDiscard = true
    var canComplete = true
    var prepared = false
    var completed = false
    override fun prepare() { prepared = true }
    override fun complete() {
        check(closed)
        if (!canComplete) throw IOException("Cannot record completion")
        completed = true
    }
    override fun open(): OutputStream {
        check(prepared)
        opened = true
        return object : OutputStream() {
            override fun write(value: Int) = bytes.write(value)
            override fun close() { closed = true }
        }
    }
    override fun discard(): Boolean { discards++; discarded.complete(Unit); return canDiscard }
}
