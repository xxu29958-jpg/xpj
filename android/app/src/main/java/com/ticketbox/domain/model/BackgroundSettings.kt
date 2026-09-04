package com.ticketbox.domain.model

enum class BackgroundSource(
    val storageKey: String,
) {
    ThemeDefault("theme_default"),
    BuiltIn("built_in"),
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

data class BackgroundTransform(
    val scale: Float = 1f,
    val offsetX: Float = 0f,
    val offsetY: Float = 0f,
)

data class BackgroundSettings(
    val source: BackgroundSource = BackgroundSource.ThemeDefault,
    val builtInBackgroundId: String? = null,
    val customImagePath: String? = null,
    val immersionMode: ImmersionMode = ImmersionMode.Balanced,
    val enableParallax: Boolean = true,
    val reduceMotion: Boolean = false,
    val transform: BackgroundTransform = BackgroundTransform(),
) {
    fun withBuiltInBackground(id: String): BackgroundSettings {
        return copy(
            source = BackgroundSource.BuiltIn,
            builtInBackgroundId = id.takeIf { it.isNotBlank() },
            customImagePath = null,
            transform = BackgroundTransform(),
        )
    }

    fun withCustomImage(path: String): BackgroundSettings {
        return copy(
            source = BackgroundSource.CustomImage,
            builtInBackgroundId = null,
            customImagePath = path.takeIf { it.isNotBlank() },
            transform = BackgroundTransform(),
        )
    }

    fun withoutBackground(): BackgroundSettings {
        return copy(
            source = BackgroundSource.ThemeDefault,
            builtInBackgroundId = null,
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
