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

enum class BackgroundCropMode(
    val storageKey: String,
    val displayName: String,
    val description: String,
) {
    Top(
        storageKey = "top",
        displayName = "上方",
        description = "保留画面上半部分，适合天空和票据截图",
    ),
    Center(
        storageKey = "center",
        displayName = "居中",
        description = "默认构图，适合大多数照片",
    ),
    Bottom(
        storageKey = "bottom",
        displayName = "下方",
        description = "保留画面下半部分，适合街景和桌面照片",
    );

    companion object {
        fun fromStorageKey(value: String?): BackgroundCropMode {
            return entries.firstOrNull { mode -> mode.storageKey == value } ?: Center
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
    val builtInBackgroundId: String? = null,
    val customImagePath: String? = null,
    val immersionMode: ImmersionMode = ImmersionMode.Balanced,
    val cropMode: BackgroundCropMode = BackgroundCropMode.Center,
    val enableParallax: Boolean = true,
    val reduceMotion: Boolean = false,
) {
    fun withBuiltInBackground(id: String): BackgroundSettings {
        return copy(
            source = BackgroundSource.BuiltIn,
            builtInBackgroundId = id.takeIf { it.isNotBlank() },
            customImagePath = null,
        )
    }

    fun withCustomImage(path: String): BackgroundSettings {
        return copy(
            source = BackgroundSource.CustomImage,
            builtInBackgroundId = null,
            customImagePath = path.takeIf { it.isNotBlank() },
        )
    }

    fun withoutBackground(): BackgroundSettings {
        return copy(
            source = BackgroundSource.ThemeDefault,
            builtInBackgroundId = null,
            customImagePath = null,
        )
    }

    fun withoutCustomImage(): BackgroundSettings = withoutBackground()
}

fun shouldUseCustomBackground(
    settings: BackgroundSettings,
    fileExists: (String) -> Boolean,
): Boolean {
    val path = settings.customImagePath?.takeIf { it.isNotBlank() } ?: return false
    return settings.source == BackgroundSource.CustomImage && fileExists(path)
}
