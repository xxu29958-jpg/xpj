package com.ticketbox.ui.screens.settings

import androidx.annotation.StringRes
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.ImmersionMode
import com.ticketbox.ui.appearance.AppearanceDefaults
import com.ticketbox.ui.appearance.BackgroundCatalog
import com.ticketbox.ui.appearance.BuiltInBackground
import com.ticketbox.ui.appearance.BuiltInBackgroundCategory
import com.ticketbox.ui.appearance.background.SurfaceRole

@StringRes
internal fun appSkinNameRes(skin: AppSkin): Int = when (skin) {
    AppSkin.Paper -> R.string.appearance_skin_name_paper
    AppSkin.Midnight -> R.string.appearance_skin_name_midnight
}

@StringRes
internal fun appSkinDescriptionRes(skin: AppSkin): Int = when (skin) {
    AppSkin.Paper -> R.string.appearance_skin_description_paper
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

/** 背景编辑器预览角色名：抽样用户最常看背景的五个面，与编辑面角色 chip 一一对应。 */
@StringRes
internal fun backgroundEditorRoleNameRes(role: SurfaceRole): Int = when (role) {
    SurfaceRole.Pending -> R.string.background_editor_role_pending
    SurfaceRole.Ledger -> R.string.background_editor_role_ledger
    SurfaceRole.Stats -> R.string.background_editor_role_stats
    SurfaceRole.Edit -> R.string.background_editor_role_edit
    SurfaceRole.Settings -> R.string.background_editor_role_settings
    // Today/Auth 不进编辑器抽样（由真实页面验收）；兜底复用流水角色名，不新造键。
    SurfaceRole.Today -> R.string.background_editor_role_ledger
    SurfaceRole.Auth -> R.string.background_editor_role_settings
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
