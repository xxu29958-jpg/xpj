package com.ticketbox.viewmodel

import com.ticketbox.data.remote.dto.RecycleBinItemDto
import com.ticketbox.data.remote.dto.RecycleBinListResponseDto
import com.ticketbox.data.remote.dto.RecycleBinRestoreResponseDto
import com.ticketbox.data.repository.LedgerFakeDao
import com.ticketbox.data.repository.LedgerFakeSettingsStore
import com.ticketbox.data.repository.LedgerFakeTokenStore
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.data.repository.LedgerStubApiFactory
import com.ticketbox.data.repository.StubApi
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.StandardTestDispatcher
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
        val repository = LedgerRepository(
            apiClient = LedgerStubApiFactory(api),
            settingsStore = store,
            tokenStore = LedgerFakeTokenStore().apply { saveToken("t") },
            expenseDao = LedgerFakeDao(),
        )
        return RecycleBinViewModel(repository)
    }

    private fun recycleItem(
        title: String = "旧工资",
        resourceId: String = "r1",
        rowVersion: Int? = 2,
    ) = RecycleBinItemDto(
        kind = "income_plan",
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
        } finally {
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
            assertNull(state.busyItemKey)
        } finally {
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
        } finally {
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
        } finally {
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
        } finally {
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
