package com.ticketbox.ui.screens.settings

import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.BackgroundSource
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class AppearanceScreenModelsTest {
    @Test
    fun summarySeparatesBackgroundKindsAndClearAction() {
        val theme = appearanceSummaryModel(BackgroundSettings())
        val builtIn = appearanceSummaryModel(BackgroundSettings().withBuiltInBackground("paper"))
        val custom = appearanceSummaryModel(
            BackgroundSettings(
                source = BackgroundSource.CustomImage,
                customImagePath = "/local/background.jpg",
            ),
        )

        assertEquals(AppearanceBackgroundKind.ThemeDefault, theme.backgroundKind)
        assertEquals(AppearanceBackgroundKind.BuiltIn, builtIn.backgroundKind)
        assertEquals(AppearanceBackgroundKind.CustomImage, custom.backgroundKind)
        assertFalse(theme.canClearCustomImage)
        assertFalse(builtIn.canClearCustomImage)
        assertTrue(custom.canClearCustomImage)
    }

    @Test
    fun summaryTreatsReducedMotionAsTheStrongestMotionState() {
        val summary = appearanceSummaryModel(
            BackgroundSettings(
                enableParallax = true,
                reduceMotion = true,
            ),
        )

        assertEquals(AppearanceMotionKind.Reduced, summary.motionKind)
    }
}
