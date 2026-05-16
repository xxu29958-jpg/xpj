package com.ticketbox.domain.model

enum class AppSkin(
    val storageKey: String,
    val displayName: String,
    val description: String,
) {
    Paper(
        storageKey = "paper",
        displayName = "纸本",
        description = "温润米白 + 茶铜",
    ),
    Mono(
        storageKey = "mono",
        displayName = "墨白",
        description = "冷灰极简",
    ),
    Midnight(
        storageKey = "midnight",
        displayName = "玄夜",
        description = "深色玻璃 + 暖金",
    );

    companion object {
        val Default: AppSkin = Paper

        // v0.10：5 套旧 skin 退役，旧 storageKey 自动映射到新 skin。
        // harbor 是旧版默认浅色入口，迁到 paper，避免升级后从浅色直接跳到深色。
        private val LEGACY_KEY_MAP: Map<String, String> = mapOf(
            "pine" to "paper",
            "pomelo" to "paper",
            "harbor" to "paper",
            "berry" to "mono",
            "night" to "midnight",
        )

        fun fromStorageKey(value: String?): AppSkin {
            if (value == null) return Default
            val resolved = LEGACY_KEY_MAP[value] ?: value
            return entries.firstOrNull { skin -> skin.storageKey == resolved } ?: Default
        }
    }
}
