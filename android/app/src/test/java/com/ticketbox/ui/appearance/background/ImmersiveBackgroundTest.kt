package com.ticketbox.ui.appearance.background

import com.ticketbox.domain.model.ImmersionMode
import kotlin.test.Test
import kotlin.test.assertTrue

class ImmersiveBackgroundTest {
    @Test
    fun editingAndSettingsProtectReadingMoreThanEverydayViews() {
        for (dark in listOf(false, true)) {
            for (mode in ImmersionMode.entries) {
                assertTrue(
                    photoContribution(mode, SurfaceRole.Edit, dark) < photoContribution(mode, SurfaceRole.Pending, dark),
                )
                assertTrue(
                    photoContribution(mode, SurfaceRole.Settings, dark) < photoContribution(mode, SurfaceRole.Stats, dark),
                )
                for (role in SurfaceRole.entries) {
                    assertTrue(
                        resolveCustomImageScrimAlpha(mode, role, dark) >= resolveScrimAlpha(mode, role),
                        "Uncontrolled photos need at least the reading protection of the built-in artwork",
                    )
                }
            }
        }
    }

    @Test
    fun focusModeReducesPhotoInterferenceWithoutRemovingThePhoto() {
        for (dark in listOf(false, true)) {
            for (role in SurfaceRole.entries) {
                val focus = photoContribution(ImmersionMode.Focus, role, dark)
                val balanced = photoContribution(ImmersionMode.Balanced, role, dark)
                val atmosphere = photoContribution(ImmersionMode.Atmosphere, role, dark)
                assertTrue(focus > 0f, "Focus must not erase the user's background")
                assertTrue(focus < balanced && balanced < atmosphere, "Modes must reduce photo interference in order")
            }
        }
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

    // The shared renderer puts the reading scrim over the photo layer. Their combined
    // contribution, not an obsolete single-layer alpha, determines photo interference.
    private fun photoContribution(mode: ImmersionMode, role: SurfaceRole, dark: Boolean): Float =
        resolveBackgroundAlpha(mode, role) * (1f - resolveCustomImageScrimAlpha(mode, role, dark))
}
