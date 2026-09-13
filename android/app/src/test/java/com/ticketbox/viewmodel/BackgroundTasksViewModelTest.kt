package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.BackgroundTaskActions
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.domain.model.BACKGROUND_TASK_COMPLETED
import com.ticketbox.domain.model.BACKGROUND_TASK_RUNNING
import com.ticketbox.domain.model.BackgroundTask
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.flow.MutableStateFlow
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
import kotlin.test.assertNull

@OptIn(ExperimentalCoroutinesApi::class)
class BackgroundTasksViewModelTest {
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
    fun refreshFailureAfterLoadedTasksKeepsRowsAndShowsStaleDataMessage() = runTest(dispatcher) {
        val initial = task(publicId = "task-1")
        val repo = FakeBackgroundTaskActions(fetchResult = Result.success(listOf(initial)))
        val vm = BackgroundTasksViewModel(repo)

        vm.refresh()
        runCurrent()
        repo.fetchResult = Result.failure(RuntimeException())

        vm.refresh()
        runCurrent()

        val state = vm.uiState.value
        assertEquals(listOf(initial), state.tasks)
        assertFalse(state.loading)
        assertEquals(UiText.res(R.string.background_tasks_message_refresh_failed_with_data), state.message)
        assertEquals(MessageTone.Danger, state.messageTone)
    }

    @Test
    fun cancelSuccessUpdatesReturnedTaskAndKeepsSuccessFeedback() = runTest(dispatcher) {
        val running = task(publicId = "task-1")
        val cancelRequested = running.copy(cancellationRequestedAt = "2026-07-05T08:00:00Z")
        val repo = FakeBackgroundTaskActions(
            fetchResult = Result.success(listOf(running)),
            cancelResult = Result.success(cancelRequested),
        )
        val vm = BackgroundTasksViewModel(repo)
        vm.refresh()
        runCurrent()

        vm.cancel(running.publicId)
        runCurrent()

        val state = vm.uiState.value
        assertEquals(listOf(cancelRequested), state.tasks)
        assertFalse(state.tasks.single().isCancellable)
        assertNull(state.busyTaskId)
        assertEquals(UiText.res(R.string.background_tasks_message_cancel_requested), state.message)
        assertEquals(MessageTone.Success, state.messageTone)
        assertEquals(1, repo.cancelCalls)
        assertEquals(1, repo.fetchCalls)
    }

    @Test
    fun cancelFailureKeepsRowsAndShowsDangerMessage() = runTest(dispatcher) {
        val running = task(publicId = "task-1")
        val repo = FakeBackgroundTaskActions(
            fetchResult = Result.success(listOf(running)),
            cancelResult = Result.failure(RuntimeException()),
        )
        val vm = BackgroundTasksViewModel(repo)
        vm.refresh()
        runCurrent()

        vm.cancel(running.publicId)
        runCurrent()

        val state = vm.uiState.value
        assertEquals(listOf(running), state.tasks)
        assertNull(state.busyTaskId)
        assertEquals(UiText.res(R.string.background_tasks_message_cancel_failed), state.message)
        assertEquals(MessageTone.Danger, state.messageTone)
        assertEquals(1, repo.cancelCalls)
    }

    @Test
    fun cancelIgnoresTerminalTasks() = runTest(dispatcher) {
        val completed = task(publicId = "task-1", status = BACKGROUND_TASK_COMPLETED)
        val repo = FakeBackgroundTaskActions(fetchResult = Result.success(listOf(completed)))
        val vm = BackgroundTasksViewModel(repo)
        vm.refresh()
        runCurrent()

        vm.cancel(completed.publicId)
        runCurrent()

        assertEquals(listOf(completed), vm.uiState.value.tasks)
        assertEquals(0, repo.cancelCalls)
    }

    @Test
    fun roleRevocationBeforeTapCannotUseCachedWritePermission() = runTest(dispatcher) {
        val running = task(publicId = "task-1")
        val repo = FakeBackgroundTaskActions(fetchResult = Result.success(listOf(running)))
        val vm = BackgroundTasksViewModel(repo)
        vm.refresh()
        runCurrent()

        repo.canModify = false
        vm.cancel(running.publicId)
        runCurrent()

        assertEquals(0, repo.cancelCalls)
    }

    @Test
    fun bindingChangeClearsOldTasksBeforeNavigationOrCancellation() = runTest(dispatcher) {
        val running = task(publicId = "task-1")
        val repo = FakeBackgroundTaskActions(fetchResult = Result.success(listOf(running)))
        val vm = BackgroundTasksViewModel(repo)
        vm.refresh()
        runCurrent()

        repo.access.value = requireNotNull(repo.access.value).let {
            it.copy(binding = it.binding.copy(ledgerId = "other", bindingRevision = "revision-2"))
        }
        runCurrent()

        assertEquals(emptyList(), vm.uiState.value.tasks)
        assertNull(vm.sourceExpenseId(running.publicId))
        vm.cancel(running.publicId)
        runCurrent()
        assertEquals(0, repo.cancelCalls)
    }

    @Test
    fun delayedOldBindingRefreshCannotReplaceNewLedgerTasks() = runTest(dispatcher) {
        val delayed = CompletableDeferred<Result<List<BackgroundTask>>>()
        val repo = FakeBackgroundTaskActions()
        repo.fetchOverride = { delayed.await() }
        val vm = BackgroundTasksViewModel(repo)
        vm.refresh()
        runCurrent()
        repo.access.value = requireNotNull(repo.access.value).let {
            it.copy(binding = it.binding.copy(ledgerId = "other", bindingRevision = "revision-2"))
        }
        runCurrent()
        val current = task(publicId = "new-ledger-task")
        repo.fetchOverride = null
        repo.fetchResult = Result.success(listOf(current))
        vm.refresh()
        runCurrent()

        delayed.complete(Result.success(listOf(task(publicId = "old-ledger-task"))))
        runCurrent()

        assertEquals(listOf(current), vm.uiState.value.tasks)
        assertFalse(vm.uiState.value.loading)
        assertNull(vm.uiState.value.message)
    }

    @Test
    fun viewerCanReadTasksButCannotRequestCancellation() = runTest(dispatcher) {
        val running = task(publicId = "task-1")
        val repo = FakeBackgroundTaskActions(
            canModify = false,
            fetchResult = Result.success(listOf(running)),
            cancelResult = Result.success(running),
        )
        val vm = BackgroundTasksViewModel(repo)

        vm.refresh()
        runCurrent()
        vm.cancel(running.publicId)
        runCurrent()

        assertFalse(vm.uiState.value.canModify)
        assertEquals(listOf(running), vm.uiState.value.tasks)
        assertEquals(1, repo.fetchCalls)
        assertEquals(0, repo.cancelCalls)
    }

    private fun task(
        publicId: String,
        status: String = BACKGROUND_TASK_RUNNING,
    ): BackgroundTask = BackgroundTask(
        publicId = publicId,
        taskType = "csv_import",
        status = status,
        progressCurrent = 1,
        progressTotal = 10,
        progressMessage = null,
        errorCode = null,
        errorMessage = null,
        createdAt = "2026-07-05T07:00:00Z",
        startedAt = null,
        completedAt = null,
        cancellationRequestedAt = null,
    )

    private class FakeBackgroundTaskActions(
        var canModify: Boolean = true,
        var fetchResult: Result<List<BackgroundTask>> = Result.success(emptyList()),
        var cancelResult: Result<BackgroundTask> = Result.failure(IllegalStateException()),
    ) : BackgroundTaskActions {
        var fetchCalls = 0
        var cancelCalls = 0
        val access = MutableStateFlow<LedgerAccessContext?>(LedgerAccessContext(
            LogicalSessionBinding("https://example.test", "ledger", "owner", "session", "revision-1"), canModify,
        ))
        var fetchOverride: (suspend () -> Result<List<BackgroundTask>>)? = null

        override fun currentAccess(): LedgerAccessContext? = access.value?.copy(canModify = canModify)
        override fun observeAccess() = access

        override suspend fun fetchBackgroundTasks(binding: LogicalSessionBinding): Result<List<BackgroundTask>> {
            fetchCalls += 1
            return fetchOverride?.invoke() ?: fetchResult
        }

        override suspend fun cancelBackgroundTask(binding: LogicalSessionBinding, publicId: String): Result<BackgroundTask> {
            cancelCalls += 1
            return cancelResult
        }
    }
}
