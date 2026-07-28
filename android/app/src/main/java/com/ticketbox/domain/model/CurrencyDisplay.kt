package com.ticketbox.domain.model

data class CurrencyDisplay(
    val homeCurrency: CurrencyCode = FxContract.HomeCurrency,
    /**
     * 服务端 record 带来但客户端支持集外的原始币种码（PR#255 R7-2，如新版服务端新增的
     * 币种）。非 null 时显示侧必须原样亮码（R8-4：原 minor 整数 + 原始码，"1200 VND"），
     * 不得用 [homeCurrency]（此时是兜底 CNY）的符号撒谎，也不得按任何已知 exponent 缩放。
     */
    val unknownCode: String? = null,
) {
    companion object {
        val Base: CurrencyDisplay = CurrencyDisplay()

        /**
         * Record 口径的 display context：按服务端 record 自带的 `homeCurrencyCode`
         * 渲染（symbol/小数位随该币种），给 record-aware 的金额输入标签 / 对账行用 ——
         * 这些位置的显示必须和解析同源于 record 币种，不能落恒 Base 的环境 display
         * （FxContract 登记局限）。空值 / 未知键回落 [Base] 同款默认。
         * 支持集外的码不再静默回落（R7-2）：记入 [unknownCode]，显示侧原样亮码。
         */
        fun forRecord(homeCurrencyCode: String?): CurrencyDisplay {
            val known = CurrencyCode.fromStorageKeyOrNull(homeCurrencyCode)
            if (known != null) return CurrencyDisplay(homeCurrency = known)
            return CurrencyDisplay(
                unknownCode = homeCurrencyCode?.trim()?.uppercase()?.takeIf { it.isNotBlank() },
            )
        }
    }
}
