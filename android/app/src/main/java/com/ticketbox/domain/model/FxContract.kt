package com.ticketbox.domain.model

object FxContract {
    /**
     * Client fallback for legacy/local rows before the backend response provides `home_currency`.
     * The backend remains the only authority for FX conversion and home amount calculation.
     *
     * 登记（B3-prep parity 切片）：硬编码 CNY 目前**无法平滑**改为读服务端 homeCurrencyCode ——
     * 服务端只在 record 级（Expense/Debt/DebtGoal/RepaymentDraft/MemberRepaymentProposal）返回
     * home 币种，客户端没有账本级/账户级的全局 home 来源；AppViewModel 也恒以
     * [CurrencyDisplay.Base] 提供 LocalCurrencyDisplay。故本兜底保留：record 可得处一律用
     * record 的 homeCurrencyCode，仅新建流（Goal/IncomePlan/首笔欠款）与空缓存搜索落到这里。
     */
    val HomeCurrency: CurrencyCode = CurrencyCode.CNY

    const val StatusReady = "ready"
    const val StatusPending = "pending"
    const val SourceBase = "base"
    const val SourceManual = "manual"
    const val BaseRateToHome = "1"
}
