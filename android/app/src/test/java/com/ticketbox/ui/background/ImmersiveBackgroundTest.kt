package com.ticketbox.ui.background

import com.ticketbox.domain.model.ImmersionMode
import kotlin.test.Test
import kotlin.test.assertTrue

class ImmersiveBackgroundTest {
    @Test
    fun editAndSettingsKeepBackgroundMoreRestrainedThanHome() {
        val home = resolveBackgroundAlpha(ImmersionMode.Atmosphere, SurfaceRole.Home)
        val edit = resolveBackgroundAlpha(ImmersionMode.Atmosphere, SurfaceRole.Edit)
        val settings = resolveBackgroundAlpha(ImmersionMode.Atmosphere, SurfaceRole.Settings)

        assertTrue(home > edit)
        assertTrue(home > settings)
        assertTrue(edit <= 0.40f)
        assertTrue(settings <= 0.36f)
    }

    @Test
    fun focusModeKeepsBackgroundSubtle() {
        val ledger = resolveBackgroundAlpha(ImmersionMode.Focus, SurfaceRole.Ledger)
        val edit = resolveBackgroundAlpha(ImmersionMode.Focus, SurfaceRole.Edit)

        assertTrue(ledger <= 0.22f)
        assertTrue(edit <= 0.18f)
    }
}
