package com.ticketbox.ui.design

import com.ticketbox.domain.model.AppSkin
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class ThemeVisualsTest {
    @Test
    fun everySkinHasCompleteThemeVisuals() {
        AppSkin.entries.forEach { skin ->
            val visuals = themeVisualsForSkin(skin)

            assertTrue(visuals.heroGradient.size >= 2, "$skin hero gradient should have at least two colors")
            assertTrue(visuals.primary.alpha > 0.99f, "$skin primary should be opaque")
            assertTrue(visuals.solidCard.alpha > 0.99f, "$skin solid card should be opaque")
            assertTrue(visuals.glassTint.alpha > 0.99f, "$skin glass tint should be opaque")
            assertTrue(visuals.shadowTint.alpha > 0.99f, "$skin shadow tint should be opaque")
        }
    }

    @Test
    fun everySkinHasLayeredBackgroundVisuals() {
        AppSkin.entries.forEach { skin ->
            val visuals = backgroundVisualsForSkin(skin)

            assertTrue(visuals.baseGradient.size >= 3, "$skin background should use layered vertical gradient")
            assertTrue(visuals.topGlowAlpha > 0f, "$skin top glow should be visible")
            assertTrue(visuals.sideGlowAlpha > 0f, "$skin side glow should be visible")
            assertTrue(visuals.bottomMist.isNotEmpty(), "$skin bottom mist should be configured")
            assertTrue(visuals.textureAlpha > 0f, "$skin texture should be configured")
        }
    }

    @Test
    fun defaultSkinRemainsHarbor() {
        assertEquals(AppSkin.Harbor, AppSkin.Default)
    }
}
