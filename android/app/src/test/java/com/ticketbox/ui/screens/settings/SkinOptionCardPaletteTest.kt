package com.ticketbox.ui.screens.settings

import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.design.themeVisualsForSkin
import com.ticketbox.ui.theme.colorSchemeForSkin
import kotlin.test.Test
import kotlin.test.assertEquals

class SkinOptionCardPaletteTest {
    @Test
    fun cardTextUsesThePreviewThemeInsteadOfTheAmbientTheme() {
        AppSkin.entries.forEach { previewSkin ->
            val scheme = colorSchemeForSkin(previewSkin)
            val palette = skinOptionCardPalette(
                scheme = scheme,
                visuals = themeVisualsForSkin(previewSkin),
                selected = false,
            )

            assertEquals(scheme.onSurface, palette.title)
            assertEquals(scheme.onSurfaceVariant, palette.description)
        }
    }
}
