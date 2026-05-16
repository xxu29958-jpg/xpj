package com.ticketbox.ui.appearance

import com.ticketbox.domain.model.AppSkin

enum class BuiltInBackgroundCategory(
    val displayName: String,
) {
    Nature("自然"),
    Emotion("情绪"),
    Minimal("极简"),
    Illustration("插画"),
}

data class BuiltInBackground(
    val id: String,
    val name: String,
    val category: BuiltInBackgroundCategory,
    val description: String,
    val gradientColors: List<Long>,
    val preferredSkin: AppSkin? = null,
)

object BackgroundCatalog {
    val entries: List<BuiltInBackground> = listOf(
        BuiltInBackground(
            id = "paper",
            name = "纸本",
            category = BuiltInBackgroundCategory.Minimal,
            description = "温润米白与茶铜纸影，和桌面账本默认视觉一致。",
            gradientColors = listOf(0xFFFBF8F1L, 0xFFF3EFE6L, 0xFFEAD8B8L),
            preferredSkin = AppSkin.Paper,
        ),
        BuiltInBackground(
            id = "paper_warm",
            name = "茶雾",
            category = BuiltInBackgroundCategory.Nature,
            description = "更明显的暖纸雾面，适合待确认和统计首页。",
            gradientColors = listOf(0xFFFFFBF3L, 0xFFECD8B5L, 0xFFC8B895L),
            preferredSkin = AppSkin.Paper,
        ),
        BuiltInBackground(
            id = "mono",
            name = "墨白",
            category = BuiltInBackgroundCategory.Minimal,
            description = "冷灰纸面，减少彩色干扰。",
            gradientColors = listOf(0xFFFAFAF8L, 0xFFF1F0EDL, 0xFFDAD9D4L),
            preferredSkin = AppSkin.Mono,
        ),
        BuiltInBackground(
            id = "mono_fog",
            name = "灰雾",
            category = BuiltInBackgroundCategory.Illustration,
            description = "低对比灰雾，适合表格和长列表。",
            gradientColors = listOf(0xFFF7F7F4L, 0xFFE3E2DDL, 0xFFB8B7B3L),
            preferredSkin = AppSkin.Mono,
        ),
        BuiltInBackground(
            id = "midnight",
            name = "玄夜",
            category = BuiltInBackgroundCategory.Nature,
            description = "深色玻璃与暖金，适合夜间。",
            gradientColors = listOf(0xFF15171CL, 0xFF1C1F25L, 0xFF8A6A3EL),
            preferredSkin = AppSkin.Midnight,
        ),
        BuiltInBackground(
            id = "midnight_gold",
            name = "暖金",
            category = BuiltInBackgroundCategory.Emotion,
            description = "深色底上的暖金光晕，保留暗色但不回到旧蓝绿。",
            gradientColors = listOf(0xFF0C0D10L, 0xFF2A2D35L, 0xFFB89564L),
            preferredSkin = AppSkin.Midnight,
        ),
    )

    private val legacyIdMap: Map<String, String> = mapOf(
        "pine_mist" to "paper",
        "harbor" to "paper",
        "pomelo_light" to "paper_warm",
        "warm_fog" to "paper_warm",
        "berry" to "mono",
        "clouds" to "mono_fog",
        "night" to "midnight",
    )

    fun find(id: String?): BuiltInBackground? {
        val resolvedId = legacyIdMap[id] ?: id
        return entries.firstOrNull { background -> background.id == resolvedId }
    }

    fun byCategory(category: BuiltInBackgroundCategory): List<BuiltInBackground> {
        return entries.filter { background -> background.category == category }
    }
}
