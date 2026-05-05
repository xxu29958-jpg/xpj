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
            id = "pine_mist",
            name = "松雾",
            category = BuiltInBackgroundCategory.Nature,
            description = "低饱和绿雾，适合夜间记账。",
            gradientColors = listOf(0xFF10231FL, 0xFF31564DL, 0xFFB8C8B7L),
            preferredSkin = AppSkin.Pine,
        ),
        BuiltInBackground(
            id = "harbor",
            name = "港湾",
            category = BuiltInBackgroundCategory.Nature,
            description = "安静蓝绿，默认推荐。",
            gradientColors = listOf(0xFF10222EL, 0xFF245A63L, 0xFFBFD7D3L),
            preferredSkin = AppSkin.Harbor,
        ),
        BuiltInBackground(
            id = "pomelo_light",
            name = "柚光",
            category = BuiltInBackgroundCategory.Emotion,
            description = "暖纸和柚子色，轻松但不过亮。",
            gradientColors = listOf(0xFFFFF5D7L, 0xFFFFC57AL, 0xFF7E5B3CL),
            preferredSkin = AppSkin.Pomelo,
        ),
        BuiltInBackground(
            id = "berry",
            name = "莓果",
            category = BuiltInBackgroundCategory.Emotion,
            description = "低亮莓色，适合短时查看。",
            gradientColors = listOf(0xFF211224L, 0xFF5D2D50L, 0xFFF2A8BFL),
            preferredSkin = AppSkin.Berry,
        ),
        BuiltInBackground(
            id = "night",
            name = "夜幕",
            category = BuiltInBackgroundCategory.Nature,
            description = "深夜蓝黑，克制耐看。",
            gradientColors = listOf(0xFF080C13L, 0xFF18253AL, 0xFF59708BL),
            preferredSkin = AppSkin.Night,
        ),
        BuiltInBackground(
            id = "paper",
            name = "纸感",
            category = BuiltInBackgroundCategory.Minimal,
            description = "暖白纸面，适合白天。",
            gradientColors = listOf(0xFFFBF7EFL, 0xFFE9DDC8L, 0xFFD0C4AFL),
            preferredSkin = AppSkin.Pomelo,
        ),
        BuiltInBackground(
            id = "warm_fog",
            name = "暖雾",
            category = BuiltInBackgroundCategory.Minimal,
            description = "轻暖灰雾，表单页更稳。",
            gradientColors = listOf(0xFFF7F1E8L, 0xFFD6D0C6L, 0xFF9EA8A3L),
            preferredSkin = AppSkin.Harbor,
        ),
        BuiltInBackground(
            id = "clouds",
            name = "云层",
            category = BuiltInBackgroundCategory.Illustration,
            description = "柔和云层感，适合统计页。",
            gradientColors = listOf(0xFFE9F1F8L, 0xFFB8CCE0L, 0xFF627B9AL),
            preferredSkin = AppSkin.Harbor,
        ),
    )

    fun find(id: String?): BuiltInBackground? {
        return entries.firstOrNull { background -> background.id == id }
    }

    fun byCategory(category: BuiltInBackgroundCategory): List<BuiltInBackground> {
        return entries.filter { background -> background.category == category }
    }
}
