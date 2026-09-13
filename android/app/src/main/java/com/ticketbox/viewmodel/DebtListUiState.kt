package com.ticketbox.viewmodel

import com.ticketbox.data.repository.PendingDebtCreation
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.domain.model.DebtKinds
import com.ticketbox.domain.model.DebtListLens
import com.ticketbox.domain.model.FxContract
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.parseAmountCents

/**
 * ADR-0049 §2 (slice 8) 欠款列表 — Android 生活流：卡片列 → 页头 CTA → 底部抽屉新建外部欠款。
 *
 * UI 形态镜像 [IncomePlanViewModel]（list + draft + submit），ViewModel 持草稿+校验态让底部
 * 抽屉保持纯渲染。债务读取按账本作用域，overlay VM 缓存且跨账本存活，故 [reload] 在每次进入时
 * 先清上一账本的欠款再拉（账本隔离，与 DebtGoalViewModel.refresh(clearStale = true) 同构）。
 */
data class DebtListUiState(
    val isLoading: Boolean = false,
    val canModify: Boolean = true,
    val debts: List<Debt> = emptyList(),
    val error: UiText? = null,
    val addDraft: DebtDraftUi = DebtDraftUi(),
    val isSubmitting: Boolean = false,
    val isParsingBill: Boolean = false,
    val flashMessage: UiText? = null,
    /** Room has acknowledged the original intent, not a confirmed Debt. Failure keeps the sheet open. */
    val addAccepted: Boolean = false,
    val pendingCreations: List<PendingDebtCreation> = emptyList(),
    /** Refreshes other canonical consumers, including the separate receivables list. */
    val creationSettlementRevision: Int = 0,
    val pendingBillParsePrefill: Boolean = false,
    /**
     * 裁决后的账本币种（null = 未确认）：非空账本取 record 级 `homeCurrencyCode`（服务端写时
     * 按 installation binding 盖章的权威值）；**空账本取列表信封的安装级 capability**
     * （PR#255 R6 P1-1：服务端 GET /api/debts 信封重发同一 binding，空账本首笔创建由此
     * 放行，打破「等首条 record」的循环论证）。两源在场却不一致 = binding 漂移（ADR-0061
     * C02 声明 installation currency 不可热切换，漂移即异常）→ 冲突 fail closed 归 null；
     * 旧服务端不下发 capability + 空账本 → 维持 R4 fail closed 归 null。新建草稿 / 账单预填
     * 的解析币种一律取本字段（兜底仅作标签显示，提交由 [homeCurrencyResolved] 守门）。
     */
    val ledgerHomeCurrency: CurrencyCode? = null,
    /**
     * 账本 home 币种是否已确认 = [ledgerHomeCurrency] 非空。false 期间新建草稿的金额解析
     * 币种只是 [FxContract.HomeCurrency] 兜底，提交被禁用（VM 与 sheet 按钮双重守门）。
     * 加载**失败**不置位（币种仍未知，创建保持禁用直到重试成功）；[reload] 账本切换时
     * 重置为 false 重新等待。
     */
    val homeCurrencyResolved: Boolean = false,
    /** 当前列表的任务视角（全账本 / 个人应付）：只用于空态文案按 lens+角色说诚实，不改变查询语义。 */
    val lens: DebtListLens = DebtListLens.Ledger,
)

data class DebtDraftUi(
    val direction: String = DebtDirections.I_OWE,
    val counterpartyLabel: String = "",
    val note: String = "",
    val amountYuanInput: String = "",
    // 8e-6e 还款类型（可选；默认 unspecified = 不分类）。仅外部债，create 透传到后端 debt_kind。
    val kind: String = DebtKinds.UNSPECIFIED,
    // §B 分期期数 + 还款周期原文（仅 kind==installment 时表单显示）。期数留空 / 非法 → 不排期；周期留空 → 后端
    // 默认每月。范围由 parsed* 收口（期数 1..600、周期 1..120，镜像后端 le 上限），kind 的 gate 在 toCreateRequest。
    val installmentCountInput: String = "",
    val installmentPeriodInput: String = "",
    val validationError: UiText? = null,
    /**
     * 金额解析口径：新建流上没有本笔 record，取账本裁决币种（[DebtListUiState.ledgerHomeCurrency]，
     * VM 构造/重绑草稿时注入；空账本=信封 capability，非空=record 级）；未确认期间落
     * [FxContract.HomeCurrency] 兜底 —— 兜底仅作标签显示，未确认下
     * [DebtListUiState.homeCurrencyResolved] 为 false，提交保持阻断（PR#255 R4 P1 / R6 P1-1）。
     * 列表响应到达后 VM 会把草稿币种重绑到裁决值（保留已输文本，PR#255 P1-2/P1-3），
     * 金额字段的显示标签同源于本字段（DebtDraftForm 绑定 draft.homeCurrency）。
     */
    val homeCurrency: CurrencyCode = FxContract.HomeCurrency,
    /**
     * 用户是否已改过草稿任一字段（VM 的 updateDraftField 置位；系统侧的账单预填不算）。
     * 仅用于权威币种重绑后的**提前重校验**：被触碰的草稿若金额在新币种下解析不出，
     * 立即亮校验错误提示修改；不再守护旧币种（P1-3 起任何草稿都随响应重绑，
     * 否则已输入内容会按 CNY 口径提交到 JPY/KRW 账本放大 100×）。
     */
    val userTouched: Boolean = false,
) {
    val noteCharacterCount: Int get() = note.codePointCount(0, note.length)
    val noteTooLong: Boolean get() = noteCharacterCount > 500

    val isValid: Boolean
        get() = counterpartyLabel.trim().isNotEmpty() && parsedAmountCents() != null && !noteTooLong

    // 元→分走共享 BigDecimal 解析器（§3 禁 Double 存金额），按 [homeCurrency] 扩位
    // （JPY 等零小数 home 不 ×100）；本金须 > 0（符号保持，分空间判等价）。
    fun parsedAmountCents(): Long? = parseAmountCents(amountYuanInput, homeCurrency)?.takeIf { it > 0 }

    // 分期期数：正整数且 1..600（镜像后端 installment_count 的 gt=0/le=600）；空 / 非数字 / 越界 → null（不排期）。
    fun parsedInstallmentCount(): Int? = installmentCountInput.trim().toIntOrNull()?.takeIf { it in 1..600 }

    // 还款周期（每几个月一期）：正整数且 1..120（镜像后端 installment_period_months le=120）；空 / 非法 → null
    // （后端默认每月）。只在 parsedInstallmentCount 也非空时随车（toCreateRequest 的 chokepoint 守这条配对）。
    fun parsedInstallmentPeriod(): Int? = installmentPeriodInput.trim().toIntOrNull()?.takeIf { it in 1..120 }
}
