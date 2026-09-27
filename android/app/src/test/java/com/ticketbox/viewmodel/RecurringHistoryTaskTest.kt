package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.RecurringActions
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.data.repository.SnapshotAccessDenial
import com.ticketbox.data.remote.dto.RecurringDefinitionDto
import com.ticketbox.data.remote.dto.RecurringHistoryPageDto
import com.ticketbox.data.remote.dto.RecurringRevisionDto
import com.ticketbox.domain.model.RecurringCandidate
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.ui.screens.recurringItem
import java.lang.reflect.Proxy
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class RecurringHistoryTaskTest {
    @Test fun externalSharedRefusalRetiresReadHistoryAndLateHistoryAndListWithoutChangingEditorEpoch() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val actions = HistoryActions()
        val vm = RecurringViewModel(actions)
        try {
            runCurrent()
            val originalEpoch = vm.uiState.value.editorEpoch
            val originalRuntime = vm.uiState.value.editorRuntimeId
            vm.historyTask.open(actions.item)
            runCurrent()
            assertEquals(listOf(9L), vm.uiState.value.history.items.map { it.rowVersion })
            val lateHistory = CompletableDeferred<Result<RecurringHistoryPageDto>>()
            val lateItems = CompletableDeferred<Result<List<RecurringItem>>>()
            actions.pendingHistory = lateHistory
            actions.pendingItems = lateItems
            vm.historyTask.more()
            vm.refresh()
            runCurrent()
            actions.readAccessDenials.emit(SnapshotAccessDenial(requireNotNull(actions.access.value).binding,
                RepositoryException("external goal refusal", httpStatusCode = 403), 1))
            runCurrent()
            assertNull(vm.uiState.value.history.publicId)
            assertTrue(vm.uiState.value.items.isEmpty())
            lateHistory.complete(Result.success(historyPage(8, null)))
            lateItems.complete(Result.success(listOf(actions.item)))
            runCurrent()
            assertTrue(vm.uiState.value.history.items.isEmpty())
            assertTrue(vm.uiState.value.items.isEmpty())
            assertEquals(originalEpoch, vm.uiState.value.editorEpoch)
            assertEquals(originalRuntime, vm.uiState.value.editorRuntimeId)
        } finally { vm.viewModelScope.cancel(); Dispatchers.resetMain() }
    }

    @Test fun pagingFailureRetryPreservesReadDefinitionsAndNeverRefreshesCurrentItems() = runTest {
        val actions = HistoryActions()
        actions.fromCache = true
        var state = RecurringHistoryState()
        val task = RecurringHistoryTask(actions, backgroundScope, { actions.access.value?.binding }, { state = it }, {})
        task.open(actions.item)
        runCurrent()
        actions.result = Result.failure(RepositoryException("offline"))
        task.more()
        runCurrent()
        assertEquals(listOf(9L), state.items.map { it.rowVersion })
        assertTrue(state.error != null)
        assertTrue(state.fromCache)
        assertEquals("2026-09-27T10:00:00Z", state.fetchedAt)
        actions.result = Result.success(historyPage(8, null))
        actions.fromCache = false
        actions.fetchedAt = "2026-09-27T11:00:00Z"
        task.retry()
        runCurrent()
        assertEquals(listOf(9L, 8L), state.items.map { it.rowVersion })
        assertTrue(state.fromCache)
        assertEquals("2026-09-27T10:00:00Z", state.fetchedAt)
        assertEquals(listOf(null, 9L, 9L), actions.cursors)
        assertEquals(0, actions.itemCalls)
        task.dismiss()
        assertTrue(state.items.isEmpty())
    }

    @Test fun historyRefusalRetiresReadListsAndTheirLateRefreshWithoutResettingSameBindingEditor() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val actions = HistoryActions()
        val vm = RecurringViewModel(actions)
        try {
            runCurrent()
            val originalEpoch = vm.uiState.value.editorEpoch
            val originalRuntime = vm.uiState.value.editorRuntimeId
            val lateItems = CompletableDeferred<Result<List<RecurringItem>>>()
            actions.pendingItems = lateItems
            vm.refresh()
            runCurrent()
            actions.result = Result.failure(RepositoryException("forbidden", httpStatusCode = 403))
            vm.historyTask.open(actions.item)
            runCurrent()
            assertNull(vm.uiState.value.history.publicId)
            assertTrue(vm.uiState.value.items.isEmpty())
            lateItems.complete(Result.success(listOf(actions.item)))
            runCurrent()
            assertTrue(vm.uiState.value.items.isEmpty())
            assertEquals(originalEpoch, vm.uiState.value.editorEpoch)
            assertEquals(originalRuntime, vm.uiState.value.editorRuntimeId)
        } finally { vm.viewModelScope.cancel(); Dispatchers.resetMain() }
    }

    @Test fun genuineBindingChangeRetiresHistoryAndKeepsExistingEditorIsolation() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val actions = HistoryActions()
        val vm = RecurringViewModel(actions)
        try {
            runCurrent()
            val epoch = vm.uiState.value.editorEpoch
            vm.historyTask.open(actions.item)
            runCurrent()
            assertEquals(listOf(9L), vm.uiState.value.history.items.map { it.rowVersion })
            val previous = requireNotNull(actions.access.value)
            actions.access.value = previous.copy(binding = previous.binding.copy(bindingRevision = "replacement"))
            runCurrent()
            assertNull(vm.uiState.value.history.publicId)
            assertTrue(vm.uiState.value.editorEpoch > epoch)
        } finally { vm.viewModelScope.cancel(); advanceUntilIdle(); Dispatchers.resetMain() }
    }
}

private class HistoryActions : RecurringActions by unsupportedHistoryActions() {
    override val readAccessDenials = MutableSharedFlow<SnapshotAccessDenial>()
    val item = recurringItem().copy(ledgerId = "owner", homeCurrencyCode = "JPY")
    val access = MutableStateFlow<LedgerAccessContext?>(LedgerAccessContext(
        LogicalSessionBinding("https://history.example", "owner", "test-owner", "session", "binding"), true))
    var result = Result.success(historyPage(9, 9))
    var fetchedAt = "2026-09-27T10:00:00Z"
    var fromCache = false
    val cursors = mutableListOf<Long?>()
    var itemCalls = 0
    var pendingItems: CompletableDeferred<Result<List<RecurringItem>>>? = null
    var pendingHistory: CompletableDeferred<Result<RecurringHistoryPageDto>>? = null
    override fun canModifyLedger() = true
    override fun observeActiveLedgerAccess() = access
    override fun observePendingIntents() = flowOf(emptyList<com.ticketbox.data.repository.RecurringPendingIntent>())
    override suspend fun history(binding: LogicalSessionBinding, publicId: String, beforeVersion: Long?):
        Result<com.ticketbox.data.repository.ReadSnapshot<RecurringHistoryPageDto>> {
        cursors += beforeVersion
        return (pendingHistory?.await() ?: result).map { com.ticketbox.data.repository.ReadSnapshot(it, fetchedAt, fromCache) }
    }
    override suspend fun items(expectedBinding: LogicalSessionBinding, status: String?, includeArchived: Boolean,
        month: String?): Result<com.ticketbox.data.repository.ReadSnapshot<List<RecurringItem>>> {
        itemCalls += 1
        return (pendingItems?.await() ?: Result.success(listOf(item)))
            .map { com.ticketbox.data.repository.ReadSnapshot(it, fetchedAt, fromCache) }
    }
    override suspend fun candidates(expectedBinding: LogicalSessionBinding) = Result.success(emptyList<RecurringCandidate>())
}

private fun historyPage(version: Long, next: Long?) = RecurringHistoryPageDto("owner", "rec-1",
    listOf(RecurringRevisionDto(version, "edit", "2026-09-19T00:00:00Z", null,
        RecurringDefinitionDto("原计划", "original", "monthly", "JPY", 1200, null, "active", "candidate"))), next)

private fun unsupportedHistoryActions(): RecurringActions = Proxy.newProxyInstance(RecurringActions::class.java.classLoader,
    arrayOf(RecurringActions::class.java)) { _, method, _ -> error("Unexpected history action: ${method.name}") } as RecurringActions
