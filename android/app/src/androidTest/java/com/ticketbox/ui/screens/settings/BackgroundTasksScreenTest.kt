package com.ticketbox.ui.screens.settings

import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.unit.Density
import androidx.lifecycle.ViewModelStore
import com.ticketbox.data.repository.BackgroundTaskActions
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.domain.model.BackgroundTask
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.BackgroundTasksViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class BackgroundTasksScreenTest {
    @get:Rule val compose = createComposeRule()
    private val store = ViewModelStore()
    private val skin = mutableStateOf(AppSkin.Paper)
    private val scale = mutableStateOf(1f)
    private val opened = mutableListOf<Long>()
    private var connectionOpened = 0

    @After fun clearViewModels() = compose.runOnIdle { store.clear() }

    @Test fun sourceRecoveryAndFailedCancellationKeepTheirOriginalTasks() {
        val original = listOf(
            task("recognized", "completed", 41),
            task("failed", "failed", 42).copy(errorMessage = "识别暂未完成，请回到原账单继续。"),
            task("import", "running", null).copy(taskType = "csv_import"),
        )
        val repo = TaskHistory(original, canModify = true)
        val vm = show(repo)
        compose.waitUntil { vm.uiState.value.tasks.size == 3 && !vm.uiState.value.loading }
        compose.onNodeWithText("进度 2/2").assertDoesNotExist()
        compose.onAllNodesWithText("任务详情")[0].performScrollTo().performClick()
        compose.onNodeWithText("进度 2/2").assertIsDisplayed()
        capture("background-task-details-paper")
        compose.onNodeWithText("收起详情").performClick()
        compose.onNodeWithText("进度 2/2").assertDoesNotExist()
        capture("background-tasks-paper")
        compose.onAllNodesWithText("打开原账单")[0].performScrollTo().performClick()
        compose.onAllNodesWithText("打开原账单")[1].performScrollTo().performClick()
        compose.runOnIdle { assertEquals(listOf(41L, 42L), opened) }
        compose.onNodeWithText("取消任务").performScrollTo().performClick()
        compose.waitUntil { repo.cancelled.size == 1 && vm.uiState.value.busyTaskId == null }
        compose.runOnIdle {
            assertEquals(original, vm.uiState.value.tasks)
            assertEquals(MessageTone.Danger, vm.uiState.value.messageTone)
            repo.failCancel = false
        }
        compose.onNodeWithText("取消任务").performScrollTo().performClick()
        compose.waitUntil { repo.cancelled.size == 2 && vm.uiState.value.busyTaskId == null }
        compose.runOnIdle {
            assertEquals(listOf("import", "import"), repo.cancelled)
            assertEquals(listOf(repo.access.value!!.binding, repo.access.value!!.binding), repo.cancelBindings)
            assertEquals("running", vm.uiState.value.tasks.last().status)
            assertFalse(vm.uiState.value.tasks.last().isCancellable)
            skin.value = AppSkin.Midnight
            scale.value = 1.8f
        }
        compose.onNodeWithText("连接检查").performScrollTo().performClick()
        compose.runOnIdle { assertEquals(1, connectionOpened) }
        capture("background-tasks-midnight-large")
    }

    @Test fun emptyAndFailedReadsRemainDistinctAndViewerCanOpenSourceWithoutCancelling() {
        val repo = TaskHistory(emptyList(), canModify = false)
        val vm = show(repo)
        compose.waitUntil { repo.fetches > 0 && !vm.uiState.value.loading }
        compose.onNodeWithText("没有后台任务").performScrollTo().assertIsDisplayed()
        capture("background-tasks-empty")
        compose.runOnIdle { repo.result = Result.failure(IllegalStateException()) }
        compose.onNodeWithText("刷新").performScrollTo().performClick()
        compose.waitUntil { vm.uiState.value.messageTone == MessageTone.Danger && !vm.uiState.value.loading }
        compose.onNodeWithText("没有后台任务").assertDoesNotExist()
        capture("background-tasks-read-failure")
        compose.runOnIdle { repo.result = Result.success(listOf(task("viewer-source", "running", 43))) }
        compose.onNodeWithText("刷新").performScrollTo().performClick()
        compose.waitUntil { vm.uiState.value.tasks.size == 1 && !vm.uiState.value.loading }
        compose.onNodeWithText("取消任务").assertDoesNotExist()
        compose.onNodeWithText("打开原账单").performScrollTo().performClick()
        compose.onNodeWithText("连接检查").performScrollTo().performClick()
        compose.runOnIdle {
            assertEquals(listOf(43L), opened)
            assertEquals(1, connectionOpened)
            assertTrue(repo.cancelled.isEmpty())
        }
    }

    private fun show(repo: TaskHistory): BackgroundTasksViewModel {
        val vm = BackgroundTasksViewModel(repo)
        store.put("tasks", vm)
        compose.setContent {
            val density = LocalDensity.current
            CompositionLocalProvider(LocalDensity provides Density(density.density, scale.value)) {
                TicketboxTheme(skin = skin.value) {
                    BackgroundTasksScreen(vm, {}, { opened += it }, { connectionOpened++ })
                }
            }
        }
        return vm
    }

    private fun capture(name: String) = saveConsumerArtPreview(name, compose.onRoot().captureToImage().asAndroidBitmap())

    private fun task(id: String, status: String, source: Long?) = BackgroundTask(
        publicId = id, taskType = "expense_enrichment", status = status,
        progressCurrent = if (status == "completed") 2 else 1, progressTotal = 2,
        progressMessage = null, errorCode = null, errorMessage = null,
        createdAt = "2026-10-04T00:00:00Z", startedAt = null, completedAt = null,
        cancellationRequestedAt = null, sourceExpenseId = source,
    )

    private class TaskHistory(tasks: List<BackgroundTask>, canModify: Boolean) : BackgroundTaskActions {
        val access = MutableStateFlow<LedgerAccessContext?>(LedgerAccessContext(
            LogicalSessionBinding("https://family.example.test", "ledger", "owner", "session", "revision"), canModify))
        var result = Result.success(tasks)
        var fetches = 0
        var failCancel = true
        val cancelled = mutableListOf<String>()
        val cancelBindings = mutableListOf<LogicalSessionBinding>()
        override fun currentAccess() = access.value
        override fun observeAccess() = access
        override suspend fun fetchBackgroundTasks(binding: LogicalSessionBinding): Result<List<BackgroundTask>> {
            check(binding == access.value?.binding)
            fetches++
            return result
        }
        override suspend fun cancelBackgroundTask(binding: LogicalSessionBinding, publicId: String): Result<BackgroundTask> {
            cancelBindings += binding
            cancelled += publicId
            return if (failCancel) Result.failure(IllegalStateException()) else Result.success(
                result.getOrThrow().single { it.publicId == publicId }.copy(cancellationRequestedAt = "2026-10-04T00:10:00Z"))
        }
    }
}
