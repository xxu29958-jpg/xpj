package com.ticketbox.ui.appearance.background

import com.ticketbox.domain.model.ImmersionMode
import kotlin.test.Test
import kotlin.test.assertTrue

class ImmersiveBackgroundTest {
    @Test
    fun editAndSettingsKeepBackgroundMoreRestrainedThanPendingAndStats() {
        val pending = resolveBackgroundAlpha(ImmersionMode.Atmosphere, SurfaceRole.Pending)
        val stats = resolveBackgroundAlpha(ImmersionMode.Atmosphere, SurfaceRole.Stats)
        val edit = resolveBackgroundAlpha(ImmersionMode.Atmosphere, SurfaceRole.Edit)
        val settings = resolveBackgroundAlpha(ImmersionMode.Atmosphere, SurfaceRole.Settings)

        assertTrue(pending > edit)
        assertTrue(stats > settings)
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

    @Test
    fun editAndSettingsCardsStayMoreSolidThanPendingAndStats() {
        val pending = resolveCardContainerAlpha(ImmersionMode.Atmosphere, SurfaceRole.Pending)
        val stats = resolveCardContainerAlpha(ImmersionMode.Atmosphere, SurfaceRole.Stats)
        val edit = resolveCardContainerAlpha(ImmersionMode.Atmosphere, SurfaceRole.Edit)
        val settings = resolveCardContainerAlpha(ImmersionMode.Atmosphere, SurfaceRole.Settings)

        assertTrue(edit > pending)
        assertTrue(settings > stats)
    }
}

