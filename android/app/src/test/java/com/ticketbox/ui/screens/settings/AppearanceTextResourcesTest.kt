package com.ticketbox.ui.screens.settings

import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.BackgroundCropMode
import com.ticketbox.domain.model.ImmersionMode
import com.ticketbox.ui.appearance.BackgroundCatalog
import com.ticketbox.ui.appearance.BuiltInBackgroundCategory
import kotlin.test.Test
import kotlin.test.assertEquals

class AppearanceTextResourcesTest {
    @Test
    fun skinAndModeLabelsResolveToResources() {
        assertEquals(R.string.appearance_skin_name_paper, appSkinNameRes(AppSkin.Paper))
        assertEquals(R.string.appearance_skin_description_midnight, appSkinDescriptionRes(AppSkin.Midnight))
        assertEquals(R.string.appearance_immersion_name_balanced, immersionModeNameRes(ImmersionMode.Balanced))
        assertEquals(R.string.appearance_immersion_description_focus, immersionModeDescriptionRes(ImmersionMode.Focus))
    }

    @Test
    fun backgroundCatalogLabelsResolveToResources() {
        val paper = requireNotNull(BackgroundCatalog.find("paper"))
        val warm = requireNotNull(BackgroundCatalog.find("paper_warm"))

        assertEquals(R.string.appearance_background_category_minimal, builtInBackgroundCategoryNameRes(BuiltInBackgroundCategory.Minimal))
        assertEquals(R.string.appearance_background_name_paper, builtInBackgroundNameRes(paper))
        assertEquals(R.string.appearance_background_description_paper_warm, builtInBackgroundDescriptionRes(warm))
        assertEquals(R.string.appearance_crop_mode_name_center, cropModeNameRes(BackgroundCropMode.Center))
        assertEquals(R.string.appearance_crop_mode_description_bottom, cropModeDescriptionRes(BackgroundCropMode.Bottom))
    }
}
