package com.ticketbox.domain.model

enum class BackgroundSource(
    val storageKey: String,
) {
    ThemeDefault("theme_default"),
    CustomImage("custom_image");

    companion object {
        fun fromStorageKey(value: String?): BackgroundSource {
            return entries.firstOrNull { source -> source.storageKey == value } ?: ThemeDefault
        }
    }
}

enum class ImmersionMode(
    val storageKey: String,
    val displayName: String,
    val description: String,
) {
    Atmosphere(
        storageKey = "atmosphere",
        displayName = "氛围",
        description = "背景更明显，适合首页和统计",
    ),
    Balanced(
        storageKey = "balanced",
        displayName = "平衡",
        description = "默认推荐，兼顾好看和清晰",
    ),
    Focus(
        storageKey = "focus",
        displayName = "专注",
        description = "弱化背景，适合长时间记账",
    );

    companion object {
        fun fromStorageKey(value: String?): ImmersionMode {
            return entries.firstOrNull { mode -> mode.storageKey == value } ?: Balanced
        }
    }
}

data class BackgroundSettings(
    val source: BackgroundSource = BackgroundSource.ThemeDefault,
    val customImagePath: String? = null,
    val immersionMode: ImmersionMode = ImmersionMode.Balanced,
    val enableParallax: Boolean = true,
    val reduceMotion: Boolean = false,
) {
    fun withCustomImage(path: String): BackgroundSettings {
        return copy(
            source = BackgroundSource.CustomImage,
            customImagePath = path.takeIf { it.isNotBlank() },
        )
    }

    fun withoutCustomImage(): BackgroundSettings {
        return copy(
            source = BackgroundSource.ThemeDefault,
            customImagePath = null,
        )
    }
}

fun shouldUseCustomBackground(
    settings: BackgroundSettings,
    fileExists: (String) -> Boolean,
): Boolean {
    val path = settings.customImagePath?.takeIf { it.isNotBlank() } ?: return false
    return settings.source == BackgroundSource.CustomImage && fileExists(path)
}
