package com.ticketbox.domain.model

import java.util.Locale

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
        /**
         * Compatibility value for persisted rows and previews that predate the
         * server home-currency contract. Production bound sessions must replace it
         * with Pair/Ledger/Switch/Invitation authority before accepting money input.
         */
        val LegacyFallback: CurrencyCode = CNY

        fun fromStorageKey(value: String?): CurrencyCode {
            if (value.isNullOrBlank()) return LegacyFallback
            return requireSupported(value)
        }

        fun requireSupported(value: String): CurrencyCode {
            val normalized = value.trim().uppercase(Locale.ROOT)
            require(
                normalized.length == ISO_CODE_LENGTH &&
                    normalized.all { it in 'A'..'Z' },
            ) {
                "Invalid ISO 4217 currency code."
            }
            return requireNotNull(entries.firstOrNull { it.storageKey == normalized }) {
                "Unsupported currency code: $normalized"
            }
        }

        private const val ISO_CODE_LENGTH = 3
    }
}
