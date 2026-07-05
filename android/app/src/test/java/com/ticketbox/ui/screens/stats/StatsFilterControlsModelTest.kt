package com.ticketbox.ui.screens.stats

import com.ticketbox.viewmodel.StatsFilterOptionsLoadState
import com.ticketbox.viewmodel.StatsUiState
import kotlin.test.Test
import kotlin.test.assertEquals

class StatsFilterControlsModelTest {
    @Test
    fun tagFilterFailureStaysVisibleWhenNoChoicesExist() {
        val model = statsTagFilterControlModel(
            state = StatsUiState(tagsLoadState = StatsFilterOptionsLoadState.Failed),
            optionLimit = 12,
        )

        assertEquals(StatsTagFilterControlKind.Failed, model.kind)
        assertEquals(emptyList(), model.choices)
    }

    @Test
    fun tagFilterLoadedEmptyIsHidden() {
        val model = statsTagFilterControlModel(
            state = StatsUiState(tagsLoadState = StatsFilterOptionsLoadState.Loaded),
            optionLimit = 12,
        )

        assertEquals(StatsTagFilterControlKind.Hidden, model.kind)
    }

    @Test
    fun tagFilterExistingChoicesWinOverRefreshFailure() {
        val model = statsTagFilterControlModel(
            state = StatsUiState(
                tags = listOf("餐饮"),
                tagsLoadState = StatsFilterOptionsLoadState.Failed,
            ),
            optionLimit = 12,
        )

        assertEquals(StatsTagFilterControlKind.Menu, model.kind)
        assertEquals(listOf("餐饮"), model.choices)
    }
}
