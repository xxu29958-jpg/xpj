package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.IncomePlanActions
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.IncomeFrequency
import com.ticketbox.domain.model.IncomePlan
import com.ticketbox.domain.model.IncomeSourceType
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.formatAmountInput
import com.ticketbox.ui.components.parseAmountCents
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.time.YearMonth

/**
 * 编辑会话：openEdit 时捕获当前 binding + 行 rowVersion 作 baseline（OCC token）；
 * 账本切换时整态随 binding 收集重置——进行中的草稿随之失效，不再写向新账本（切账本失权）。
 * [sourceAmountCents] 仅用于币种晚解析时的后补种子（弱网点了行才等到 capability 的路径）。
 */
data class IncomePlanEditSession(
    val publicId: String,
    val baselineRowVersion: Long,
    val binding: LogicalSessionBinding,
    val sourceAmountCents: Long,
    val draft: IncomePlanDraftUi,
)

data class IncomePlanEditUiState(
    val session: IncomePlanEditSession? = null,
    val isSubmitting: Boolean = false,
    /** 一次性 ack：submit/archiveFromEdit 真正成功后置 true；屏幕只在这时关编辑器并 dismiss()。 */
    val succeeded: Boolean = false,
    /** 账本币种仍在解析（晚解析窗口）：编辑器金额位显示「正在准备」而非无币种裸输入框。 */
    val currencyPending: Boolean = false,
    val flashMessage: UiText? = null,
)

/**
 * W2-C 收入编辑的伴随 ViewModel（与列表 VM 分离，同 DebtRepaymentHistoryViewModel 先例）：
 * 直连 [IncomePlanActions.update]（OCC baseline + origin binding，不假离线承诺）；
 * 归档收进编辑器（archiveFromEdit），成功才关会话，失败留草稿。
 */
class IncomePlanEditViewModel(
    private val repository: IncomePlanActions,
    private val debts: DebtActions,
    private val onDataChanged: () -> Unit = {},
) : ViewModel() {

    private val _state = MutableStateFlow(IncomePlanEditUiState())
    val state: StateFlow<IncomePlanEditUiState> = _state.asStateFlow()
    private var bindingGeneration = 0
    private var activeBinding: LogicalSessionBinding? = null
    private var activeCanModify = false
    private var homeCurrency: CurrencyCode? = null
    private var homeCurrencyBinding: LogicalSessionBinding? = null

    init {
        viewModelScope.launch {
            repository.observeActiveLedgerAccess()
                .distinctUntilChanged()
                .collect { access ->
                    activeBinding = access?.binding
                    activeCanModify = access?.canModify ?: false
                    bindingGeneration += 1
                    _state.value = IncomePlanEditUiState(currencyPending = access != null)
                    // R12-D + R14-6 同源裁决：币种在收集内挂起解析并盖上所属 binding——
                    // openEdit 只接受与打开时 binding 同一份的币种（漂移间隙 fail closed 归 null，
                    // 不拿旧账本的币种给新 binding 的编辑种子）。
                    homeCurrency = resolveLedgerCurrency(debts.listDebts().getOrNull())
                    homeCurrencyBinding = access?.binding
                    reseedOpenSessionDraft()
                    _state.update { it.copy(currencyPending = false) }
                }
        }
    }

    /** 币种晚解析闭合：已开会话属当前 binding、尚未持币种且金额仍空白时补种子；
     *  用户已输入的金额不覆盖。 */
    private fun reseedOpenSessionDraft() {
        val session = _state.value.session ?: return
        if (session.binding != homeCurrencyBinding) return
        if (session.draft.homeCurrency != null) return
        val currency = homeCurrency ?: return
        _state.update { state ->
            state.copy(
                session = session.copy(
                    draft = session.draft.copy(
                        homeCurrency = currency,
                        amountYuanInput = session.draft.amountYuanInput.ifBlank {
                            formatAmountInput(session.sourceAmountCents, currency)
                        },
                    ),
                ),
            )
        }
    }

    fun openEdit(plan: IncomePlan) {
        val binding = activeBinding ?: return
        if (!activeCanModify) return
        // busy 期间不切 target：在途提交的结果只归属原会话（sheet 忙碌时行不可点，此为双守门）。
        if (_state.value.isSubmitting) return
        val currency = homeCurrency.takeIf { homeCurrencyBinding == binding }
        _state.update {
            it.copy(
                session = IncomePlanEditSession(
                    publicId = plan.publicId,
                    baselineRowVersion = plan.rowVersion,
                    binding = binding,
                    sourceAmountCents = plan.amountCents,
                    draft = IncomePlanDraftUi(
                        label = plan.label,
                        sourceType = plan.sourceType,
                        frequency = plan.frequency,
                        incomeMonthInput = plan.incomeMonth ?: YearMonth.now().toString(),
                        amountYuanInput = currency
                            ?.let { code -> formatAmountInput(plan.amountCents, code) }
                            .orEmpty(),
                        payDayInput = plan.payDay.toString(),
                        homeCurrency = currency,
                    ),
                ),
                succeeded = false,
            )
        }
    }

    fun updateDraftField(field: IncomePlanDraftField, value: String) {
        _state.update { state ->
            val session = state.session ?: return@update state
            val draft = session.draft
            val nextDraft = when (field) {
                IncomePlanDraftField.Label -> draft.copy(label = value)
                IncomePlanDraftField.IncomeMonth -> draft.copy(incomeMonthInput = value)
                IncomePlanDraftField.Amount -> {
                    // R14-2 镜像：币种已注入时即时报解析失败。
                    val parseFailed = draft.homeCurrency != null && value.isNotBlank() &&
                        parseAmountCents(value, draft.homeCurrency) == null
                    return@update state.copy(
                        session = session.copy(
                            draft = draft.copy(
                                amountYuanInput = value,
                                validationError = if (parseFailed) {
                                    UiText.res(R.string.expense_edit_amount_invalid)
                                } else {
                                    null
                                },
                            ),
                        ),
                    )
                }
                IncomePlanDraftField.PayDay -> draft.copy(payDayInput = value)
            }
            state.copy(session = session.copy(draft = nextDraft.copy(validationError = null)))
        }
    }

    /** 选择类草稿字段（来源类型 / 频率）：频率切换连带清掉旧校验错误（月份/金额标签口径随频率变）。 */
    fun updateDraftChoice(source: IncomeSourceType? = null, frequency: IncomeFrequency? = null) {
        mutateDraft { draft ->
            when {
                source != null -> draft.copy(sourceType = source)
                frequency != null -> draft.copy(frequency = frequency, validationError = null)
                else -> draft
            }
        }
    }

    fun shiftIncomeMonth(deltaMonths: Long) {
        mutateDraft { draft ->
            val current = runCatching {
                YearMonth.parse(draft.incomeMonthInput.trim())
            }.getOrDefault(YearMonth.now())
            draft.copy(
                incomeMonthInput = current.plusMonths(deltaMonths).toString(),
                validationError = null,
            )
        }
    }

    /**
     * 币种未确认时的手动重试（编辑器「正在准备/未确认」状态行的恢复入口）：按当前 binding
     * 重新解析并补种子；已持币种则无事可做。解析仍 fail closed——失败只回到「未确认可重试」，
     * 不落兜底币种。
     */
    fun retryCurrencyResolution() {
        val binding = activeBinding ?: return
        if (homeCurrencyBinding == binding && homeCurrency != null) return
        _state.update { it.copy(currencyPending = true) }
        viewModelScope.launch {
            homeCurrency = resolveLedgerCurrency(debts.listDebts().getOrNull())
            homeCurrencyBinding = binding
            reseedOpenSessionDraft()
            _state.update { it.copy(currencyPending = false) }
        }
    }

    fun dismiss() {
        // busy 期间吞掉退场：此刻清会话会让迟到的在途结果落到下一个打开的会话上（settlement 归属）。
        if (_state.value.isSubmitting) return
        _state.update { it.copy(session = null, isSubmitting = false, succeeded = false) }
    }

    fun dismissFlash() {
        _state.update { it.copy(flashMessage = null) }
    }

    fun submit() {
        val session = _state.value.session ?: return
        if (_state.value.isSubmitting) return
        if (session.draft.homeCurrency == null) {
            // R12-D：币种未确认禁写（不落 CNY 兜底）。
            mutateDraft {
                it.copy(validationError = UiText.res(R.string.currency_unconfirmed_write_blocked))
            }
            return
        }
        val patch = session.draft.toPatchOrNull(session.baselineRowVersion)
        if (patch == null) {
            mutateDraft { it.copy(validationError = UiText.res(R.string.income_plan_validation_error)) }
            return
        }
        val binding = bindingGeneration
        _state.update { it.copy(isSubmitting = true) }
        viewModelScope.launch {
            val result = repository.update(session.binding, session.publicId, patch)
            if (binding != bindingGeneration) return@launch
            result.fold(
                onSuccess = {
                    _state.update {
                        it.copy(
                            isSubmitting = false,
                            succeeded = true,
                            flashMessage = UiText.res(R.string.income_plan_updated),
                        )
                    }
                    onDataChanged()
                },
                onFailure = { err ->
                    mutateDraft {
                        it.copy(validationError = err.toUiText(R.string.income_plan_update_failed))
                    }
                    _state.update { it.copy(isSubmitting = false) }
                },
            )
        }
    }

    /** 编辑器内的归档：同一 archive 端点 + 打开时的 baseline rowVersion；成功才关会话。 */
    fun archiveFromEdit() {
        val session = _state.value.session ?: return
        if (_state.value.isSubmitting) return
        val binding = bindingGeneration
        _state.update { it.copy(isSubmitting = true) }
        viewModelScope.launch {
            val result = repository.archive(session.binding, session.publicId, session.baselineRowVersion)
            if (binding != bindingGeneration) return@launch
            result.fold(
                onSuccess = {
                    _state.update {
                        it.copy(
                            isSubmitting = false,
                            session = null,
                            succeeded = true,
                            flashMessage = UiText.res(R.string.income_plan_archived),
                        )
                    }
                    onDataChanged()
                },
                onFailure = { err ->
                    mutateDraft { it.copy(validationError = err.toUiText(R.string.error_generic)) }
                    _state.update { it.copy(isSubmitting = false) }
                },
            )
        }
    }

    private fun mutateDraft(transform: (IncomePlanDraftUi) -> IncomePlanDraftUi) {
        _state.update { state ->
            val session = state.session ?: return@update state
            state.copy(session = session.copy(draft = transform(session.draft)))
        }
    }
}
