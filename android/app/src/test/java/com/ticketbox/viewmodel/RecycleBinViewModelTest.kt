package com.ticketbox.viewmodel

import com.ticketbox.data.remote.dto.RecycleBinItemDto
import com.ticketbox.data.remote.dto.RecycleBinListResponseDto
import com.ticketbox.data.remote.dto.RecycleBinRestoreResponseDto
import com.ticketbox.data.repository.LedgerFakeDao
import com.ticketbox.data.repository.LedgerFakeSettingsStore
import com.ticketbox.data.repository.ledgerSessionFixture
import com.ticketbox.data.repository.testLedgerRepository
import com.ticketbox.data.repository.LedgerStubApiFactory
import com.ticketbox.data.repository.StubApi
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class RecycleBinViewModelTest {

    private val ledger = "L_family"

    private fun harness(api: StubApi, role: String = "member"): RecycleBinViewModel {
        val store = LedgerFakeSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveActiveLedger(ledger, "家庭账本")
            capturedRole = role
        }
        val repository = testLedgerRepository(
            apiClient = LedgerStubApiFactory(api),
            settingsStore = store,
            tokenStore = ledgerSessionFixture(ledger, "家庭账本", role = role, token = "t"),
            expenseDao = LedgerFakeDao(),
        )
        return RecycleBinViewModel(repository)
    }

    private fun recycleItem(
        title: String = "旧工资",
        resourceId: String = "r1",
        rowVersion: Int? = 2,
        kind: String = "income_plan",
    ) = RecycleBinItemDto(
        kind = kind,
        kindLabel = "收入",
        resourceId = resourceId,
        title = title,
        detail = "2026-06 到账 · ¥1234.00",
        removedAt = "2026-06-29T00:00:00Z",
        retentionLabel = "长期保留",
        expectedRowVersion = rowVersion,
    )

    @Test
    fun refreshLoadsRecycleBinItems() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = StubApi().apply {
                recycleBinResult = RecycleBinListResponseDto(
                    items = listOf(recycleItem()),
                    shortWindowCount = 1,
                )
            }
            val vm = harness(api)

            vm.refresh()
            val state = vm.uiState.first { it.items.isNotEmpty() }

            assertEquals(listOf("旧工资"), state.items.map { it.title })
            assertEquals(1, state.shortWindowCount)
            assertEquals(1, api.recycleBinRefreshCount.size)
            assertTrue(state.canModify)
            assertNull(state.message)
            assertEquals(MessageTone.Neutral, state.messageTone)
        } finally {
            advanceUntilIdle()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun restoreCallsApiThenRefreshes() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = StubApi().apply {
                recycleBinResult = RecycleBinListResponseDto(items = emptyList(), shortWindowCount = 0)
                recycleBinRestoreResult = RecycleBinRestoreResponseDto(message = "收入记录已恢复。")
            }
            val vm = harness(api)
            val item = recycleItem().toDomain()

            vm.restore(item)
            val state = vm.uiState.first { it.message != null }

            assertEquals("income_plan", api.recycleBinRestoreRequests.single().kind)
            assertEquals("r1", api.recycleBinRestoreRequests.single().resourceId)
            assertEquals(2, api.recycleBinRestoreRequests.single().expectedRowVersion)
            assertEquals(1, api.recycleBinRefreshCount.size)
            assertEquals(emptyList(), state.items)
            assertEquals(UiText.raw("收入记录已恢复。"), state.message)
            assertEquals(MessageTone.Success, state.messageTone)
            assertNull(state.busyItemKey)
            assertEquals(1, state.changedRevision)
            // 收入记录恢复不改写确认流水行 —— 流水行 revision 保持 0。
            assertEquals(0, state.expenseRowsRestoredRevision)
        } finally {
            advanceUntilIdle()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun restoreTagMutationBumpsExpenseRowsRevision() = runTest {
        // tag_mutation 恢复会在后端重放确认流水的 Expense.tags 行，必须额外
        // bump 流水行 revision，让账本行重同步（其余 kind 不 bump，见上测试）。
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = StubApi().apply {
                recycleBinResult = RecycleBinListResponseDto(items = emptyList(), shortWindowCount = 0)
                recycleBinRestoreResult = RecycleBinRestoreResponseDto(message = "标签改动已撤销。")
            }
            val vm = harness(api)
            val item = recycleItem(kind = "tag_mutation").toDomain()

            vm.restore(item)
            val state = vm.uiState.first { it.message != null }

            assertEquals("tag_mutation", api.recycleBinRestoreRequests.single().kind)
            assertEquals(1, state.changedRevision)
            assertEquals(1, state.expenseRowsRestoredRevision)
        } finally {
            advanceUntilIdle()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun restoreSuccessKeepsRestoredRowRemovedWhenRefreshFails() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val restoredItem = recycleItem(title = "旧工资", resourceId = "r1")
            val remainingItem = recycleItem(title = "旧预算", resourceId = "r2")
            val api = StubApi().apply {
                recycleBinResult = RecycleBinListResponseDto(
                    items = listOf(restoredItem, remainingItem),
                    shortWindowCount = 1,
                )
                recycleBinRestoreResult = RecycleBinRestoreResponseDto(message = "收入记录已恢复。")
            }
            val vm = harness(api)

            vm.refresh()
            vm.uiState.first { it.items.size == 2 }
            api.recycleBinError = RuntimeException("offline")
            vm.restore(restoredItem.toDomain())
            val state = vm.uiState.first { it.loadFailed && it.busyItemKey == null }

            assertEquals(2, api.recycleBinRefreshCount.size)
            assertEquals(listOf("旧预算"), state.items.map { it.title })
            assertEquals(1, state.shortWindowCount)
            assertTrue(state.loadFailed)
            assertEquals(MessageTone.Danger, state.messageTone)
            assertEquals(1, state.changedRevision)
        } finally {
            advanceUntilIdle()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun restoreAsViewerIsNoOp() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = StubApi()
            val vm = harness(api, role = "viewer")

            vm.restore(recycleItem().toDomain())

            assertTrue(api.recycleBinRestoreRequests.isEmpty())
            assertEquals(0, vm.uiState.value.changedRevision)
        } finally {
            advanceUntilIdle()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun refreshFailureMarksLoadFailed() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = StubApi().apply { recycleBinError = RuntimeException("boom") }
            val vm = harness(api)

            vm.refresh()
            val state = vm.uiState.first { it.message != null }

            assertTrue(state.loadFailed)
            assertEquals(emptyList(), state.items)
            assertEquals(MessageTone.Danger, state.messageTone)
        } finally {
            advanceUntilIdle()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun restoreFailureSurfacesMessageAndClearsBusy() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val api = StubApi().apply { recycleBinRestoreError = RuntimeException("boom") }
            val vm = harness(api)

            vm.restore(recycleItem().toDomain())
            val state = vm.uiState.first { it.message != null }

            assertEquals(1, api.recycleBinRestoreRequests.size)
            assertNull(state.busyItemKey)
            assertEquals(MessageTone.Danger, state.messageTone)
        } finally {
            advanceUntilIdle()
            Dispatchers.resetMain()
        }
    }

    private fun RecycleBinItemDto.toDomain() = com.ticketbox.domain.model.RecycleBinItem(
        kind = kind,
        kindLabel = kindLabel,
        resourceId = resourceId,
        title = title,
        detail = detail,
        removedAt = removedAt,
        retentionLabel = retentionLabel,
        expectedRowVersion = expectedRowVersion,
    )
}
