package com.ticketbox.ui.screens.settings

import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.BackgroundSource

internal enum class AppearanceBackgroundKind {
    ThemeDefault,
    BuiltIn,
    CustomImage,
}

internal enum class AppearanceMotionKind {
    Dynamic,
    Static,
    Reduced,
}

internal data class AppearanceSummaryModel(
    val backgroundKind: AppearanceBackgroundKind,
    val motionKind: AppearanceMotionKind,
    val canClearCustomImage: Boolean,
)

internal fun appearanceSummaryModel(settings: BackgroundSettings): AppearanceSummaryModel =
    AppearanceSummaryModel(
        backgroundKind = when (settings.source) {
            BackgroundSource.ThemeDefault -> AppearanceBackgroundKind.ThemeDefault
            BackgroundSource.BuiltIn -> AppearanceBackgroundKind.BuiltIn
            BackgroundSource.CustomImage -> AppearanceBackgroundKind.CustomImage
        },
        motionKind = when {
            settings.reduceMotion -> AppearanceMotionKind.Reduced
            settings.enableParallax -> AppearanceMotionKind.Dynamic
            else -> AppearanceMotionKind.Static
        },
        canClearCustomImage = settings.source == BackgroundSource.CustomImage &&
            !settings.customImagePath.isNullOrBlank(),
    )
