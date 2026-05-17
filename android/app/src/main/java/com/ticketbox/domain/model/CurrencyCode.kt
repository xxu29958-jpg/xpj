package com.ticketbox.domain.model

/**
 * 支持记录和展示的币种。
 *
 * 多币种记账语义由后端权威返回的 `homeAmountCents`、`homeCurrency`、
 * `originalCurrencyCode`、`originalAmountMinor` 和冻结汇率字段承载。
 * 本枚举只定义支持的币种代码和本地格式化参数，不包含汇率或折算逻辑。
 */
enum class CurrencyCode(
    val storageKey: String,
    val symbol: String,
    val displayName: String,
    val localeTag: String,
) {
    CNY(storageKey = "CNY", symbol = "¥", displayName = "人民币", localeTag = "zh-CN"),
    USD(storageKey = "USD", symbol = "$", displayName = "美元", localeTag = "en-US"),
    EUR(storageKey = "EUR", symbol = "€", displayName = "欧元", localeTag = "de-DE"),
    GBP(storageKey = "GBP", symbol = "£", displayName = "英镑", localeTag = "en-GB"),
    JPY(storageKey = "JPY", symbol = "¥", displayName = "日元", localeTag = "ja-JP"),
    HKD(storageKey = "HKD", symbol = "HK$", displayName = "港币", localeTag = "zh-HK"),
    KRW(storageKey = "KRW", symbol = "₩", displayName = "韩元", localeTag = "ko-KR");

    val minorUnitDigits: Int
        get() = if (this == JPY || this == KRW) 0 else 2

    val noFractionDigits: Boolean
        get() = minorUnitDigits == 0

    companion object {
        val Default: CurrencyCode = CNY

        fun fromStorageKey(value: String?): CurrencyCode {
            if (value.isNullOrBlank()) return Default
            val normalized = value.trim().uppercase()
            return entries.firstOrNull { it.storageKey == normalized } ?: Default
        }
    }
}
