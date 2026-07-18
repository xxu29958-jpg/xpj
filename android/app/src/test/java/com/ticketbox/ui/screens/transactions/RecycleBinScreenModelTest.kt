package com.ticketbox.ui.screens.transactions

import com.ticketbox.domain.model.RecycleBinItem
import com.ticketbox.viewmodel.RecycleBinUiState
import kotlin.test.Test
import kotlin.test.assertEquals

class RecycleBinScreenModelTest {
    @Test
    fun summaryAndBodyStatePreserveVisibleDataSemantics() {
        assertEquals(
            RecycleBinSummaryModel(totalCount = 3, shortWindowCount = 2, longTermCount = 1),
            recycleBinSummaryModel(itemCount = 3, shortWindowCount = 2),
        )
        assertEquals(
            RecycleBinSummaryModel(totalCount = 3, shortWindowCount = 3, longTermCount = 0),
            recycleBinSummaryModel(itemCount = 3, shortWindowCount = 8),
        )
        assertEquals(
            RecycleBinSummaryModel(totalCount = 0, shortWindowCount = 0, longTermCount = 0),
            recycleBinSummaryModel(itemCount = -1, shortWindowCount = -2),
        )
        assertEquals(
            RecycleBinBodyState.Loading,
            recycleBinBodyState(RecycleBinUiState(loading = true)),
        )
        assertEquals(
            RecycleBinBodyState.LoadFailed,
            recycleBinBodyState(RecycleBinUiState(loadFailed = true)),
        )
        assertEquals(
            RecycleBinBodyState.Empty,
            recycleBinBodyState(RecycleBinUiState()),
        )
        assertEquals(
            RecycleBinBodyState.Content,
            recycleBinBodyState(
                RecycleBinUiState(
                    items = listOf(recycleBinItem()),
                    loading = true,
                    loadFailed = true,
                ),
            ),
        )
    }

    private fun recycleBinItem() = RecycleBinItem(
        kind = "budget",
        kindLabel = "预算",
        resourceId = "budget-1",
        title = "餐饮预算",
        detail = "每月预算",
        removedAt = "2026-07-18T00:00:00Z",
        retentionLabel = "长期保留",
        expectedRowVersion = 1,
    )
}
