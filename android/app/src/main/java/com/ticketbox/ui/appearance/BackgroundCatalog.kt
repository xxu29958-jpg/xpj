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
            description = "冷白纸面与低对比层次，长时间整理账单也不刺眼。",
            gradientColors = listOf(0xFFF7F8F6L, 0xFFF4F6F3L, 0xFFE7ECE8L),
            preferredSkin = AppSkin.Paper,
        ),
        BuiltInBackground(
            id = "paper_warm",
            name = "茶雾",
            category = BuiltInBackgroundCategory.Nature,
            description = "更明显的暖纸雾面，适合待确认和统计首页。",
            gradientColors = listOf(0xFFF8F7F2L, 0xFFEDE8DDL, 0xFFD8D0C1L),
            preferredSkin = AppSkin.Paper,
        ),
        BuiltInBackground(
            id = "mono",
            name = "墨白",
            category = BuiltInBackgroundCategory.Minimal,
            description = "冷灰纸面，减少彩色干扰。",
            gradientColors = listOf(0xFFF7F8F7L, 0xFFF3F5F4L, 0xFFDDE2DFL),
            preferredSkin = AppSkin.Mono,
        ),
        BuiltInBackground(
            id = "mono_fog",
            name = "灰雾",
            category = BuiltInBackgroundCategory.Illustration,
            description = "低对比灰雾，适合表格和长列表。",
            gradientColors = listOf(0xFFF5F7F6L, 0xFFE7EBE8L, 0xFFC8D0CBL),
            preferredSkin = AppSkin.Mono,
        ),
        BuiltInBackground(
            id = "midnight",
            name = "玄夜",
            category = BuiltInBackgroundCategory.Nature,
            description = "深色纸面与低饱和绿，适合夜间核对账单。",
            gradientColors = listOf(0xFF151A17L, 0xFF111513L, 0xFF29483FL),
            preferredSkin = AppSkin.Midnight,
        ),
        BuiltInBackground(
            id = "midnight_gold",
            name = "暖金",
            category = BuiltInBackgroundCategory.Emotion,
            description = "深色底上的暖金光晕，保留暗色但不回到旧蓝绿。",
            gradientColors = listOf(0xFF0F1311L, 0xFF202722L, 0xFF6D5A3EL),
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
