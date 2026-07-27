package com.ticketbox.domain.model

data class CurrencyDisplay(
    val homeCurrency: CurrencyCode = FxContract.HomeCurrency,
) {
    companion object {
        val Base: CurrencyDisplay = CurrencyDisplay()

        /**
         * Record 口径的 display context：按服务端 record 自带的 `homeCurrencyCode`
         * 渲染（symbol/小数位随该币种），给 record-aware 的金额输入标签 / 对账行用 ——
         * 这些位置的显示必须和解析同源于 record 币种，不能落恒 Base 的环境 display
         * （FxContract 登记局限）。空值 / 未知键回落 [Base] 同款默认。
         */
        fun forRecord(homeCurrencyCode: String?): CurrencyDisplay =
            CurrencyDisplay(homeCurrency = CurrencyCode.fromStorageKey(homeCurrencyCode))
    }
}
