package com.ticketbox.ui.screens.settings

import androidx.annotation.StringRes
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.BackgroundCropMode
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.ImmersionMode
import com.ticketbox.ui.appearance.AppearanceDefaults
import com.ticketbox.ui.appearance.BackgroundCatalog
import com.ticketbox.ui.appearance.BuiltInBackground
import com.ticketbox.ui.appearance.BuiltInBackgroundCategory

@StringRes
internal fun appSkinNameRes(skin: AppSkin): Int = when (skin) {
    AppSkin.Paper -> R.string.appearance_skin_name_paper
    AppSkin.Mono -> R.string.appearance_skin_name_mono
    AppSkin.Midnight -> R.string.appearance_skin_name_midnight
}

@StringRes
internal fun appSkinDescriptionRes(skin: AppSkin): Int = when (skin) {
    AppSkin.Paper -> R.string.appearance_skin_description_paper
    AppSkin.Mono -> R.string.appearance_skin_description_mono
    AppSkin.Midnight -> R.string.appearance_skin_description_midnight
}

@StringRes
internal fun immersionModeNameRes(mode: ImmersionMode): Int = when (mode) {
    ImmersionMode.Atmosphere -> R.string.appearance_immersion_name_atmosphere
    ImmersionMode.Balanced -> R.string.appearance_immersion_name_balanced
    ImmersionMode.Focus -> R.string.appearance_immersion_name_focus
}

@StringRes
internal fun immersionModeDescriptionRes(mode: ImmersionMode): Int = when (mode) {
    ImmersionMode.Atmosphere -> R.string.appearance_immersion_description_atmosphere
    ImmersionMode.Balanced -> R.string.appearance_immersion_description_balanced
    ImmersionMode.Focus -> R.string.appearance_immersion_description_focus
}

@StringRes
internal fun cropModeNameRes(mode: BackgroundCropMode): Int = when (mode) {
    BackgroundCropMode.Top -> R.string.appearance_crop_mode_name_top
    BackgroundCropMode.Center -> R.string.appearance_crop_mode_name_center
    BackgroundCropMode.Bottom -> R.string.appearance_crop_mode_name_bottom
}

@StringRes
internal fun cropModeDescriptionRes(mode: BackgroundCropMode): Int = when (mode) {
    BackgroundCropMode.Top -> R.string.appearance_crop_mode_description_top
    BackgroundCropMode.Center -> R.string.appearance_crop_mode_description_center
    BackgroundCropMode.Bottom -> R.string.appearance_crop_mode_description_bottom
}

@StringRes
internal fun builtInBackgroundCategoryNameRes(category: BuiltInBackgroundCategory): Int = when (category) {
    BuiltInBackgroundCategory.Nature -> R.string.appearance_background_category_nature
    BuiltInBackgroundCategory.Emotion -> R.string.appearance_background_category_emotion
    BuiltInBackgroundCategory.Minimal -> R.string.appearance_background_category_minimal
    BuiltInBackgroundCategory.Illustration -> R.string.appearance_background_category_illustration
}

@StringRes
internal fun builtInBackgroundNameRes(background: BuiltInBackground): Int = when (background.id) {
    "paper" -> R.string.appearance_background_name_paper
    "paper_warm" -> R.string.appearance_background_name_paper_warm
    "mono" -> R.string.appearance_background_name_mono
    "mono_fog" -> R.string.appearance_background_name_mono_fog
    "midnight" -> R.string.appearance_background_name_midnight
    "midnight_gold" -> R.string.appearance_background_name_midnight_gold
    else -> R.string.appearance_background_source_builtin
}

@StringRes
internal fun builtInBackgroundDescriptionRes(background: BuiltInBackground): Int = when (background.id) {
    "paper" -> R.string.appearance_background_description_paper
    "paper_warm" -> R.string.appearance_background_description_paper_warm
    "mono" -> R.string.appearance_background_description_mono
    "mono_fog" -> R.string.appearance_background_description_mono_fog
    "midnight" -> R.string.appearance_background_description_midnight
    "midnight_gold" -> R.string.appearance_background_description_midnight_gold
    else -> R.string.appearance_background_source_builtin
}

@Composable
internal fun backgroundSourceLabel(settings: BackgroundSettings): String {
    val builtIn = BackgroundCatalog.find(settings.builtInBackgroundId)
    return if (builtIn != null && settings.source == com.ticketbox.domain.model.BackgroundSource.BuiltIn) {
        stringResource(builtInBackgroundNameRes(builtIn))
    } else {
        stringResource(AppearanceDefaults.backgroundSourceFallbackLabelRes(settings.source))
    }
}
