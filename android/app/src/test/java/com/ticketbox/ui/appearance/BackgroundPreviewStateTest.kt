package com.ticketbox.ui.appearance

import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.ImmersionMode
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class BackgroundPreviewStateTest {
    @Test
    fun changingPreviewImmersionDoesNotChangeAppliedSettings() {
        val applied = BackgroundSettings()
        val preview = BackgroundPreviewState(
            previewSettings = applied,
            appliedSettings = applied,
        ).withImmersionMode(ImmersionMode.Atmosphere)

        assertEquals(ImmersionMode.Atmosphere, preview.previewSettings.immersionMode)
        assertEquals(ImmersionMode.Balanced, preview.appliedSettings.immersionMode)
        assertTrue(preview.isDirty())
    }

    @Test
    fun cancelPreviewCanKeepAppliedSettingsUnchanged() {
        val applied = BackgroundSettings()
        val preview = BackgroundPreviewState(
            previewSettings = applied.withBuiltInBackground("harbor"),
            appliedSettings = applied,
        )

        assertEquals(applied, preview.appliedSettings)
        assertFalse(preview.appliedSettings.source == preview.previewSettings.source)
    }
}
