package com.ticketbox.ui.components

import kotlin.test.Test
import kotlin.test.assertEquals

class AppTagChoicesTest {
    @Test
    fun tagChoicesTrimDropBlankAndDedupeIgnoringCase() {
        assertEquals(
            listOf("Food", "Travel"),
            buildAppTagFilterChoices(
                availableTags = listOf(" Food ", "", "food", "Travel", " travel "),
                selectedTag = "",
            ),
        )
    }

    @Test
    fun tagChoicesPinStaleSelectedTag() {
        assertEquals(
            listOf("Hidden", "Food", "Travel"),
            buildAppTagFilterChoices(
                availableTags = listOf("Food", "Travel"),
                selectedTag = " Hidden ",
            ),
        )
    }

    @Test
    fun tagChoicesPinSelectedTagBeforeApplyingLimit() {
        assertEquals(
            listOf("Tag 13", "Tag 1", "Tag 2"),
            buildAppTagFilterChoices(
                availableTags = (1..13).map { "Tag $it" },
                selectedTag = "Tag 13",
                limit = 3,
            ),
        )
    }

    @Test
    fun tagChoicesTreatNegativeLimitAsEmpty() {
        assertEquals(
            emptyList(),
            buildAppTagFilterChoices(
                availableTags = listOf("Food"),
                selectedTag = "Food",
                limit = -1,
            ),
        )
    }
}
