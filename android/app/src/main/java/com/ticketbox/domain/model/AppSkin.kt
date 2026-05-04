package com.ticketbox.domain.model

enum class AppSkin(
    val storageKey: String,
    val displayName: String,
    val description: String,
) {
    Pine(
        storageKey = "pine",
        displayName = "松雾",
        description = "安静耐看的深绿底色",
    ),
    Pomelo(
        storageKey = "pomelo",
        displayName = "柚光",
        description = "暖黄、薄荷和珊瑚色点缀",
    ),
    Harbor(
        storageKey = "harbor",
        displayName = "港湾",
        description = "青蓝、米白和橙色的冷暖平衡",
    ),
    Berry(
        storageKey = "berry",
        displayName = "莓果",
        description = "偏柔和的莓粉和浅绿",
    );

    companion object {
        val Default: AppSkin = Pine

        fun fromStorageKey(value: String?): AppSkin {
            return entries.firstOrNull { skin -> skin.storageKey == value } ?: Default
        }
    }
}
