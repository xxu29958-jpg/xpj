package com.ticketbox.domain.model

enum class AppSkin(
    val storageKey: String,
    val displayName: String,
    val description: String,
) {
    Pine(
        storageKey = "pine",
        displayName = "松雾",
        description = "深绿夜色",
    ),
    Pomelo(
        storageKey = "pomelo",
        displayName = "柚光",
        description = "暖纸感",
    ),
    Harbor(
        storageKey = "harbor",
        displayName = "港湾",
        description = "海蓝暖光",
    ),
    Berry(
        storageKey = "berry",
        displayName = "莓果",
        description = "莓粉柔光",
    );

    companion object {
        val Default: AppSkin = Harbor

        fun fromStorageKey(value: String?): AppSkin {
            return entries.firstOrNull { skin -> skin.storageKey == value } ?: Default
        }
    }
}
