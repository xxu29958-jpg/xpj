package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.DebtDraft
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtBillSuggestion
import com.ticketbox.domain.model.DebtCounterpartyTypes
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.domain.model.DebtKinds
import com.ticketbox.domain.model.DebtSourceTypes
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.parseAmountCents
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlin.math.abs

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
) {
    val isValid: Boolean
        get() = counterpartyLabel.trim().isNotEmpty() && parsedAmountCents() != null

    // 元→分走共享 BigDecimal 解析器（§3 禁 Double 存金额）；本金须 > 0（符号保持，分空间判等价）。
    fun parsedAmountCents(): Long? = parseAmountCents(amountYuanInput)?.takeIf { it > 0 }

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
     */
    fun reload() {
        _state.update {
            it.copy(debts = emptyList(), error = null, canModify = repository.canModifyLedger())
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
                onSuccess = { debts ->
                    _state.update {
                        it.copy(
                            isLoading = false,
                            canModify = repository.canModifyLedger(),
                            debts = debts,
                            error = null,
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
            state.copy(addDraft = updated)
        }
    }

    fun resetDraft() {
        _state.update {
            it.copy(
                addDraft = DebtDraftUi(),
                isSubmitting = false,
                addSucceeded = false,
                pendingBillParsePrefill = false,
            )
        }
    }

    fun markBillParsePreparing(): Boolean {
        val current = _state.value
        if (!current.canModify || current.isParsingBill || current.isSubmitting) return false
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
                    val filled = DebtDraftUi()
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
                            addDraft = DebtDraftUi(),
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
        amountYuanInput = suggestion.principalAmountCents?.toYuanInput().orEmpty(),
        kind = if (parsedInstallmentCount != null) DebtKinds.INSTALLMENT else DebtKinds.UNSPECIFIED,
        installmentCountInput = parsedInstallmentCount?.toString().orEmpty(),
        installmentPeriodInput = parsedInstallmentPeriod?.toString().orEmpty(),
        validationError = null,
    )
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

private fun Long.toYuanInput(): String {
    val yuan = this / 100
    val fen = abs(this % 100)
    return if (fen == 0L) yuan.toString() else "$yuan.${fen.toString().padStart(2, '0')}"
}

private fun parseBillDoneRes(suggestion: DebtBillSuggestion): Int =
    if (suggestion.hasAnyPrefill) {
        R.string.debt_bill_parse_done
    } else {
        R.string.debt_bill_parse_empty
    }
