package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.DebtDraft
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtBillSuggestion
import com.ticketbox.domain.model.DebtCounterpartyTypes
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.domain.model.DebtKinds
import com.ticketbox.domain.model.DebtSourceTypes
import com.ticketbox.domain.model.FxContract
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.formatMinorAmountInput
import com.ticketbox.ui.components.parseAmountCents
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

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
    /**
     * 一次性信号：[submitDraft] 真正成功后置 true；底部抽屉屏只在它为 true 时关闭(关时调
     * [resetDraft] 一并清掉本信号 + 草稿,镜像 LedgerViewModel.manualCreateDone 的 ack 约定)。
     * failure 不置位 → 抽屉保留、表单错误可见(修「乐观关闭」:旧逻辑按本地 `addDraft.isValid`
     * 关闭、无视 createDebt() 结果,且 onClose 的 resetDraft() 抹掉 onFailure 刚写的
     * validationError → 欠款静默没建)。
     */
    val addSucceeded: Boolean = false,
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
)

data class DebtDraftUi(
    val direction: String = DebtDirections.I_OWE,
    val counterpartyLabel: String = "",
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
    val isValid: Boolean
        get() = counterpartyLabel.trim().isNotEmpty() && parsedAmountCents() != null

    // 元→分走共享 BigDecimal 解析器（§3 禁 Double 存金额），按 [homeCurrency] 扩位
    // （JPY 等零小数 home 不 ×100）；本金须 > 0（符号保持，分空间判等价）。
    fun parsedAmountCents(): Long? = parseAmountCents(amountYuanInput, homeCurrency)?.takeIf { it > 0 }

    // 分期期数：正整数且 1..600（镜像后端 installment_count 的 gt=0/le=600）；空 / 非数字 / 越界 → null（不排期）。
    fun parsedInstallmentCount(): Int? = installmentCountInput.trim().toIntOrNull()?.takeIf { it in 1..600 }

    // 还款周期（每几个月一期）：正整数且 1..120（镜像后端 installment_period_months le=120）；空 / 非法 → null
    // （后端默认每月）。只在 parsedInstallmentCount 也非空时随车（toCreateRequest 的 chokepoint 守这条配对）。
    fun parsedInstallmentPeriod(): Int? = installmentPeriodInput.trim().toIntOrNull()?.takeIf { it in 1..120 }
}

class DebtListViewModel(
    private val repository: DebtActions,
) : ViewModel() {

    private val _state = MutableStateFlow(DebtListUiState(canModify = repository.canModifyLedger()))
    val state: StateFlow<DebtListUiState> = _state.asStateFlow()

    // Monotonic load token (mirrors DebtGoalViewModel): a refresh applies its result only if it is
    // still the latest. Overlapping refreshes — init + reload on overlay (re-)entry + the refresh
    // after a create — each bump it, so a slow earlier list fetch can't overwrite newer data (the
    // just-created debt, or a switched ledger's debts). Every bump is a refresh, so a superseded
    // load is always replaced by a newer refresh that owns the loading flag — it just drops.
    private var loadGeneration = 0L

    init {
        refresh()
    }

    /**
     * 进入 overlay 时调用：先清掉上一账本残留的欠款再拉，避免在新账本下短暂看到旧账本的欠款
     * （账本隔离；overlay VM 跨账本切换存活，见 DebtGoalViewModel.refresh(clearStale = true)）。
     * 草稿一并重置：旧账本草稿文本若存活到新账本，响应落地时会被 rebind 静默重解释
     * （JPY 账本的 "1200" 落到 CNY 账本变 120000 minor，100× —— PR#255 R5 P2）；与
     * 打开新建抽屉必先 [resetDraft] 同一语义。
     */
    fun reload() {
        _state.update {
            it.copy(
                debts = emptyList(),
                error = null,
                canModify = repository.canModifyLedger(),
                // 新账本币种未知，创建重新禁用到本次拉取成功（PR#255 P1-3）。
                homeCurrencyResolved = false,
                ledgerHomeCurrency = null,
                // 账本切换即作废旧账本草稿：币种重绑前的兜底口径文本不得跨账本存活（PR#255 R5 P2）。
                addDraft = DebtDraftUi(),
            )
        }
        refresh()
    }

    fun refresh() {
        val gen = ++loadGeneration
        _state.update { it.copy(isLoading = true, error = null) }
        viewModelScope.launch {
            val result = repository.listDebts()
            // Drop a load superseded by a newer refresh (which set isLoading and owns clearing it).
            if (gen != loadGeneration) return@launch
            result.fold(
                onSuccess = { page ->
                    val debts = page.debts
                    // 同源裁决（PR#255 R6 P1-1 / R7-1，ADR-0061 C02/C03）：非空账本取 record 级
                    // 权威值；空账本取列表信封的安装级 capability（空账本首笔创建由此放行，
                    // 打破「等首条 record」循环）；两源冲突 / 缺失（旧服务端空账本）→ null，
                    // fail closed 不重绑、创建保持阻断。R7-1 起校验**全行** record 码集合：
                    // 混币（>1 已知码）或任一未知键同样归 null。
                    val ledgerCurrency = resolveLedgerCurrency(
                        recordCodes = debts.map { it.homeCurrencyCode },
                        capabilityCode = page.ledgerHomeCurrencyCode,
                    )
                    _state.update {
                        it.copy(
                            isLoading = false,
                            canModify = repository.canModifyLedger(),
                            debts = debts,
                            error = null,
                            addDraft = ledgerCurrency?.let(it.addDraft::rebindHomeCurrency) ?: it.addDraft,
                            homeCurrencyResolved = ledgerCurrency != null,
                            ledgerHomeCurrency = ledgerCurrency,
                        )
                    }
                },
                onFailure = { err ->
                    _state.update {
                        it.copy(isLoading = false, error = err.toUiText(R.string.debt_list_load_failed))
                    }
                },
            )
        }
    }

    fun updateDraftField(field: DebtDraftField, value: String) {
        _state.update { state ->
            val updated = when (field) {
                DebtDraftField.Direction -> state.addDraft.copy(direction = value, validationError = null)
                DebtDraftField.Counterparty -> state.addDraft
                    .copy(counterpartyLabel = value, validationError = null)
                    .withInheritedModelFrom(state.debts)
                DebtDraftField.Amount -> state.addDraft.copy(amountYuanInput = value, validationError = null)
                DebtDraftField.Kind -> state.addDraft.copy(kind = value, validationError = null)
                DebtDraftField.InstallmentCount -> state.addDraft.copy(installmentCountInput = value, validationError = null)
                DebtDraftField.InstallmentPeriod -> state.addDraft.copy(installmentPeriodInput = value, validationError = null)
            }
            state.copy(addDraft = updated.copy(userTouched = true))
        }
    }

    fun resetDraft() {
        _state.update {
            it.copy(
                addDraft = DebtDraftUi(homeCurrency = it.ledgerHomeCurrency ?: FxContract.HomeCurrency),
                isSubmitting = false,
                addSucceeded = false,
                pendingBillParsePrefill = false,
            )
        }
    }

    fun markBillParsePreparing(): Boolean {
        val current = _state.value
        // homeCurrencyResolved 门与 submitDraft 对齐（PR#255 R5 P3）：币种未确认时预填必按
        // 兜底口径格式化，重绑后金额文本静默变义（JPY 账本的 "1200.00" 重绑后非法/变值）。
        if (!current.canModify || current.isParsingBill || current.isSubmitting || !current.homeCurrencyResolved) {
            return false
        }
        _state.update { it.copy(isParsingBill = true, error = null) }
        return true
    }

    fun billParsePreparationFailed() {
        _state.update {
            it.copy(
                isParsingBill = false,
                error = UiText.res(R.string.debt_bill_parse_failed),
            )
        }
    }

    fun parseDebtBillImage(fileName: String, contentType: String?, bytes: ByteArray) {
        val current = _state.value
        if (!current.isParsingBill && !markBillParsePreparing()) return
        viewModelScope.launch {
            repository.parseDebtBillImage(fileName, contentType, bytes).fold(
                onSuccess = { suggestion ->
                    val filled = DebtDraftUi(homeCurrency = _state.value.ledgerHomeCurrency ?: FxContract.HomeCurrency)
                        .prefillFrom(suggestion)
                        .withInheritedModelFrom(_state.value.debts)
                    _state.update {
                        it.copy(
                            addDraft = filled,
                            isParsingBill = false,
                            pendingBillParsePrefill = true,
                            flashMessage = UiText.res(parseBillDoneRes(suggestion)),
                            error = null,
                        )
                    }
                },
                onFailure = { err ->
                    _state.update {
                        it.copy(
                            isParsingBill = false,
                            error = err.toUiText(R.string.debt_bill_parse_failed),
                        )
                    }
                },
            )
        }
    }

    fun ackBillParsePrefill() {
        _state.update { it.copy(pendingBillParsePrefill = false) }
    }

    fun submitDraft() {
        val state = _state.value
        // 币种未确认（初始/切换加载未成功，或空账本没有 record 级权威币种）禁止提交：
        // 兜底 CNY 口径送到 JPY/KRW 账本会放大 100×（PR#255 P1-3 / R4 P1；sheet 按钮
        // 同步禁用，此处为兜底防线）。
        if (!state.homeCurrencyResolved) return
        val draft = state.addDraft.withInheritedModelFrom(state.debts)
        val amount = draft.parsedAmountCents()
        val label = draft.counterpartyLabel.trim()
        if (label.isEmpty() || amount == null) {
            _state.update {
                it.copy(
                    addDraft = it.addDraft.copy(
                        validationError = UiText.res(R.string.debt_create_validation_error),
                    ),
                )
            }
            return
        }
        _state.update { it.copy(isSubmitting = true) }
        viewModelScope.launch {
            val result = repository.createDebt(
                DebtDraft(
                    direction = draft.direction,
                    counterpartyLabel = label,
                    principalAmountCents = amount,
                    debtKind = draft.kind,
                    installmentCount = draft.parsedInstallmentCount(),
                    installmentPeriodMonths = draft.parsedInstallmentPeriod(),
                ),
            )
            result.fold(
                onSuccess = {
                    _state.update {
                        it.copy(
                            isSubmitting = false,
                            addDraft = DebtDraftUi(homeCurrency = it.ledgerHomeCurrency ?: FxContract.HomeCurrency),
                            flashMessage = UiText.res(R.string.debt_create_added),
                            addSucceeded = true,
                        )
                    }
                    refresh()
                },
                onFailure = { err ->
                    _state.update {
                        it.copy(
                            isSubmitting = false,
                            addDraft = it.addDraft.copy(
                                validationError = err.toUiText(R.string.debt_create_failed),
                            ),
                        )
                    }
                },
            )
        }
    }

    fun dismissFlash() {
        _state.update { it.copy(flashMessage = null) }
    }
}

private data class DebtModelTemplate(
    val debtKind: String,
    val installmentCountInput: String = "",
    val installmentPeriodInput: String = "",
)

private fun DebtDraftUi.prefillFrom(suggestion: DebtBillSuggestion): DebtDraftUi {
    val parsedInstallmentCount = suggestion.installmentCount?.toIntOrNullIn(1, 600)
    val parsedInstallmentPeriod = suggestion.installmentPeriodMonths?.toIntOrNullIn(1, 120)
    return copy(
        counterpartyLabel = suggestion.merchant?.trim().orEmpty(),
        // R8-2：provider 声明金额单位为 **CNY 分**（debt_bill_parse_service prompt：两位小数
        // 分单位，mock ¥1,200.00→120000）。草稿绑定非 CNY（JPY/KRW 零小数账本）时预填会把
        // 分当账本 minor 提交（100×）→ 金额字段不预填、留用户手填（其它字段保留预填）；
        // 不做换算（无 FX 路径，换算属新设计）。CNY 账本维持原口径（零小数 home 不 ÷100）。
        amountYuanInput = suggestion.principalAmountCents
            ?.takeIf { homeCurrency == CurrencyCode.CNY }
            ?.let { formatMinorAmountInput(it, homeCurrency) }
            .orEmpty(),
        kind = if (parsedInstallmentCount != null) DebtKinds.INSTALLMENT else DebtKinds.UNSPECIFIED,
        installmentCountInput = parsedInstallmentCount?.toString().orEmpty(),
        installmentPeriodInput = parsedInstallmentPeriod?.toString().orEmpty(),
        validationError = null,
    )
}

/**
 * 列表响应落地后把草稿币种重绑到账本权威值（PR#255 P1-3）：任何草稿都重绑 ——
 * 保留用户已输文本，但不再让旧币种（CNY 兜底）存活到提交路径。被用户触碰过且
 * 已输金额在新币种下解析不出的，立即亮校验错误（提前重校验），等用户按新标签
 * 修正；其余情况静默重绑。账本切换的跨账本残留不由这里兜底 —— [DebtListViewModel.reload]
 * 已把草稿一并重置（PR#255 R5 P2），本函数只覆盖本账本加载窗口内新输/预填的草稿。
 */
private fun DebtDraftUi.rebindHomeCurrency(authoritative: CurrencyCode): DebtDraftUi {
    val rebound = copy(homeCurrency = authoritative)
    val amountBroken = userTouched &&
        authoritative != homeCurrency &&
        amountYuanInput.isNotBlank() &&
        rebound.parsedAmountCents() == null
    return if (amountBroken) {
        rebound.copy(validationError = UiText.res(R.string.debt_create_validation_error))
    } else {
        rebound
    }
}

private fun DebtDraftUi.withInheritedModelFrom(debts: List<Debt>): DebtDraftUi {
    if (kind != DebtKinds.UNSPECIFIED) return this
    val template = debts.modelTemplateFor(counterpartyLabel) ?: return this
    return copy(
        kind = template.debtKind,
        installmentCountInput = template.installmentCountInput,
        installmentPeriodInput = template.installmentPeriodInput,
    )
}

private fun List<Debt>.modelTemplateFor(label: String): DebtModelTemplate? {
    val normalized = label.normalizedDebtLabel()
    if (normalized.isEmpty()) return null
    val templates = asSequence()
        .filter { it.counterpartyType == DebtCounterpartyTypes.EXTERNAL }
        .filter { it.sourceType == DebtSourceTypes.MANUAL }
        .filter { !it.isVoided }
        .filter { it.counterpartyLabel.normalizedDebtLabel() == normalized }
        .mapNotNull { it.toModelTemplate() }
        .distinct()
        .toList()
    return templates.singleOrNull()
}

private fun Debt.toModelTemplate(): DebtModelTemplate? {
    if (debtKind == DebtKinds.UNSPECIFIED) return null
    return DebtModelTemplate(
        debtKind = debtKind,
        installmentCountInput = if (debtKind == DebtKinds.INSTALLMENT) {
            installmentCount?.toString().orEmpty()
        } else {
            ""
        },
        installmentPeriodInput = if (debtKind == DebtKinds.INSTALLMENT) {
            installmentPeriodMonths?.toString().orEmpty()
        } else {
            ""
        },
    )
}

private fun String?.normalizedDebtLabel(): String =
    orEmpty().filterNot { it.isWhitespace() }.lowercase()

private fun Long.toIntOrNullIn(min: Int, max: Int): Int? =
    takeIf { it in min.toLong()..max.toLong() }?.toInt()

private fun parseBillDoneRes(suggestion: DebtBillSuggestion): Int =
    if (suggestion.hasAnyPrefill) {
        R.string.debt_bill_parse_done
    } else {
        R.string.debt_bill_parse_empty
    }
