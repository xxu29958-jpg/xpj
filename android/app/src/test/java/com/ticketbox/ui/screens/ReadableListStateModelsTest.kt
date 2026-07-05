package com.ticketbox.ui.screens

import com.ticketbox.domain.model.UiText
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class ReadableListStateModelsTest {

    @Test
    fun bodyStatePrioritizesReadableRowsThenLoadingFailureAndEmpty() {
        val error = UiText.raw("load failed")

        assertEquals(
            ReadableListBodyState.Content,
            readableListBodyState(hasRows = true, isLoading = true, error = error),
        )
        assertEquals(
            ReadableListBodyState.Loading,
            readableListBodyState(hasRows = false, isLoading = true, error = error),
        )
        assertEquals(
            ReadableListBodyState.LoadFailed,
            readableListBodyState(hasRows = false, isLoading = false, error = error),
        )
        assertEquals(
            ReadableListBodyState.Empty,
            readableListBodyState(hasRows = false, isLoading = false, error = null),
        )
        assertEquals(error, readableListInlineError(hasRows = true, error = error))
        assertNull(readableListInlineError(hasRows = false, error = error))
    }
}
