package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.viewModelScope
import com.squareup.moshi.JsonClass
import com.ticketbox.R
import com.ticketbox.data.repository.IncomePlanActions
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.PendingIncomePlanSubmission
import com.ticketbox.data.repository.toUpdateRequest
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.IncomeFrequency
import com.ticketbox.domain.model.IncomePlan
import com.ticketbox.domain.model.IncomeSourceType
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.formatAmountInput
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.Job
import java.time.YearMonth

/**
 * 编辑会话：openEdit 时捕获当前 binding + 行 rowVersion 作 baseline（OCC token）；
 * 完整身份切换时隐藏旧会话；原输入仍归属原身份，权限往返不重置 baseline。
 * [sourceAmountCents] 用于核对缺少币种的旧缓存；只从同一计划版本补齐记录币种。
 */
@JsonClass(generateAdapter = true)
data class IncomePlanEditSession(
    val publicId: String,
    val baselineRowVersion: Long,
    val binding: LogicalSessionBinding,
    val sourceAmountCents: Long,
    val baseline: IncomePlan,
    val draft: IncomePlanDraftUi,
) {
    fun matchesSubmission(pending: PendingIncomePlanSubmission): Boolean {
        val intent = pending.intent ?: return false
        val patch = draft.toPatchOrNull(baselineRowVersion) ?: return false
        return pending.hasSupportedIntent && intent.planPublicId == publicId &&
            pending.row.expectedRowVersion == baselineRowVersion && pending.row.ownerKey == binding.ownerKey &&
            pending.row.ledgerId == binding.ledgerId &&
            com.ticketbox.data.repository.canonicalServerOriginOrNull(pending.row.serverUrl) ==
                com.ticketbox.data.repository.canonicalServerOriginOrNull(binding.serverUrl) &&
            intent.originSessionGeneration == binding.sessionGeneration && intent.originBindingRevision == binding.bindingRevision &&
            intent.originalLabel == baseline.label && intent.originalAmountCents == baseline.amountCents &&
            intent.homeCurrencyCode == draft.homeCurrency?.storageKey &&
            intent.request == patch.toUpdateRequest().copy(expectedRowVersion = 0)
    }

    /** Resolve only the recorded baseline currency, never a later financial version. */
    fun resolveCurrency(current: IncomePlan?, failure: Throwable?): IncomePlanEditSession {
        val currency = CurrencyCode.fromStorageKeyOrNull(current?.homeCurrencyCode)
        val verified = current != null && current.rowVersion == baselineRowVersion &&
            current.amountCents == sourceAmountCents && currency != null
        return copy(
            baseline = if (verified) requireNotNull(current) else baseline,
            draft = if (verified) draft.copy(homeCurrency = currency,
                amountYuanInput = draft.amountYuanInput.ifBlank { formatAmountInput(sourceAmountCents, requireNotNull(currency)) },
                validationError = null) else draft.copy(validationError =
                    failure?.toUiText(R.string.error_generic)
                        ?: UiText.res(R.string.income_plan_currency_refresh_required)),
        )
    }
}

data class IncomePlanEditUiState(
    val session: IncomePlanEditSession? = null,
    val canModify: Boolean = false,
    val isSubmitting: Boolean = false,
    /** 一次性 ack：submit/archiveFromEdit 真正成功后置 true；屏幕只在这时关编辑器并 dismiss()。 */
    val succeeded: Boolean = false,
    /** 账本币种仍在解析（晚解析窗口）：编辑器金额位显示「正在准备」而非无币种裸输入框。 */
    val currencyPending: Boolean = false,
    val flashMessage: UiText? = null,
)

/**
 * W2-C 收入编辑的伴随 ViewModel（与列表 VM 分离，同 DebtRepaymentHistoryViewModel 先例）：
 * 编辑先持久化原月份、金额、OCC 与身份，再由待同步队列发布；
 * 归档收进编辑器（archiveFromEdit），成功才关会话，失败留草稿。
 */
class IncomePlanEditViewModel(
    private val repository: IncomePlanActions,
    private val onDataChanged: () -> Unit = {},
    savedStateHandle: SavedStateHandle = SavedStateHandle(),
) : ViewModel() {

    private val _state = MutableStateFlow(IncomePlanEditUiState())
    val state: StateFlow<IncomePlanEditUiState> = _state.asStateFlow()
    private var bindingGeneration = 0
    private var activeBinding: LogicalSessionBinding? = null
    private var activeCanModify = false
    private val draftStore = IncomePlanEditDraftStore(savedStateHandle)
    private val inFlight = mutableMapOf<LogicalSessionBinding, IncomePlanEditSession>()
    private var restorationJob: Job? = null

    init {
        viewModelScope.launch {
            repository.observeActiveLedgerAccess()
                .distinctUntilChanged()
                .collect { access ->
                    val nextBinding = access?.binding
                    activeCanModify = access?.canModify ?: false
                    if (nextBinding != activeBinding) {
                        restorationJob?.cancel()
                        activeBinding = nextBinding
                        bindingGeneration += 1
                        val generation = bindingGeneration
                        // Hide the old identity before Room can suspend; permission-only updates stay responsive.
                        _state.value = IncomePlanEditUiState(canModify = activeCanModify)
                        if (nextBinding != null) {
                            restorationJob = viewModelScope.launch restore@{
                                val submissions = repository.observeSubmissions(nextBinding).first()
                                if (generation != bindingGeneration || nextBinding != activeBinding) return@restore
                                draftStore.removePublished(nextBinding, submissions)
                                _state.value = IncomePlanEditUiState(
                                    session = inFlight[nextBinding] ?: draftStore.read(nextBinding),
                                    isSubmitting = nextBinding in inFlight,
                                    canModify = activeCanModify,
                                )
                            }
                        }
                    } else {
                        _state.update { it.copy(canModify = activeCanModify) }
                    }
                }
        }
    }

    fun openEdit(plan: IncomePlan, intentMonth: String) {
        val binding = activeBinding ?: return
        if (!activeCanModify) return
        if (restorationJob?.isActive == true) return
        // busy 期间不切 target：在途提交的结果只归属原会话（sheet 忙碌时行不可点，此为双守门）。
        if (_state.value.isSubmitting) return
        val currency = CurrencyCode.fromStorageKeyOrNull(plan.homeCurrencyCode)
        _state.update {
            it.copy(
                session = draftStore.read(binding, plan.publicId) ?: IncomePlanEditSession(
                    publicId = plan.publicId,
                    baselineRowVersion = plan.rowVersion,
                    binding = binding,
                    sourceAmountCents = plan.amountCents,
                    baseline = plan,
                    draft = IncomePlanDraftUi(
                        intentMonth = intentMonth,
                        label = plan.label,
                        sourceType = plan.sourceType,
                        frequency = plan.frequency,
                        incomeMonthInput = plan.incomeMonth ?: intentMonth,
                        amountYuanInput = currency
                            ?.let { code -> formatAmountInput(plan.amountCents, code) }
                            .orEmpty(),
                        payDayInput = plan.payDay.toString(),
                        homeCurrency = currency,
                    ),
                ),
                succeeded = false,
                currencyPending = false,
            )
        }
        _state.value.session?.let(draftStore::write)
    }

    fun updateDraftField(field: IncomePlanDraftField, value: String) {
        mutateDraft { draft ->
            when (field) {
                IncomePlanDraftField.Label -> draft.copy(label = value)
                IncomePlanDraftField.IncomeMonth -> draft.copy(incomeMonthInput = value)
                IncomePlanDraftField.Amount -> draft.copy(amountYuanInput = value).withAmountValidation()
                IncomePlanDraftField.PayDay -> draft.copy(payDayInput = value)
            }.let { if (field == IncomePlanDraftField.Amount) it else it.copy(validationError = null) }
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
            }.getOrElse {
                runCatching { YearMonth.parse(draft.intentMonth) }.getOrNull() ?: return@mutateDraft draft
            }
            draft.copy(
                incomeMonthInput = current.plusMonths(deltaMonths).toString(),
                validationError = null,
            )
        }
    }

    /** Refresh an unknown currency from the same plan version, preserving the entered draft. */
    fun retryCurrencyResolution() {
        val session = _state.value.session ?: return
        if (_state.value.isSubmitting || session.draft.homeCurrency != null || _state.value.currencyPending) return
        val generation = bindingGeneration
        _state.update { it.copy(currencyPending = true) }
        viewModelScope.launch {
            val result = repository.listIncluding(session.binding, session.baseline.status)
            if (generation != bindingGeneration) return@launch
            val current = result.getOrNull()?.value?.firstOrNull { it.publicId == session.publicId }
            _state.update { state ->
                val currentSession = state.session ?: return@update state
                if (state.isSubmitting) return@update state.copy(currencyPending = false)
                if (currentSession.publicId != session.publicId || currentSession.baselineRowVersion != session.baselineRowVersion) return@update state
                state.copy(currencyPending = false,
                    session = currentSession.resolveCurrency(current, result.exceptionOrNull()))
            }
            _state.value.session?.let(draftStore::write)
        }
    }

    fun dismiss() {
        // busy 期间吞掉退场：此刻清会话会让迟到的在途结果落到下一个打开的会话上（settlement 归属）。
        if (_state.value.isSubmitting) return
        _state.update { it.copy(session = null, isSubmitting = false, succeeded = false) }
    }

    /** Explicit Cancel discards input; Back, swipe and navigation keep it available. */
    fun cancel() {
        if (_state.value.isSubmitting) return
        _state.value.session?.let(draftStore::remove)
        dismiss()
    }

    fun dismissFlash() {
        _state.update { it.copy(flashMessage = null) }
    }

    fun submit() {
        val session = _state.value.session ?: return
        if (_state.value.isSubmitting || _state.value.succeeded || !activeCanModify || session.binding != activeBinding) return
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
        inFlight[session.binding] = session
        _state.update { it.copy(isSubmitting = true) }
        viewModelScope.launch {
            val result = repository.enqueueUpdate(session.binding, session.baseline, patch, requireNotNull(session.draft.homeCurrency))
            inFlight.remove(session.binding)
            if (result.isSuccess) draftStore.remove(session)
            if (session.binding != activeBinding || _state.value.session != session) return@launch
            result.fold(
                onSuccess = {
                    _state.update {
                        it.copy(
                            isSubmitting = false,
                            succeeded = true,
                            flashMessage = UiText.res(R.string.income_plan_edit_saved_locally),
                        )
                    }
                    onDataChanged()
                },
                onFailure = { err ->
                    _state.update { it.copy(isSubmitting = false, session = session.copy(
                        draft = session.draft.copy(validationError = err.toUiText(R.string.income_plan_update_failed)))) }
                },
            )
        }
    }

    /** 编辑器内的归档：同一 archive 端点 + 打开时的 baseline rowVersion；成功才关会话。 */
    fun archiveFromEdit() {
        val session = _state.value.session ?: return
        if (_state.value.isSubmitting || _state.value.succeeded || !activeCanModify || session.binding != activeBinding) return
        inFlight[session.binding] = session
        _state.update { it.copy(isSubmitting = true) }
        viewModelScope.launch {
            val result = repository.archive(session.binding, session.publicId, session.baselineRowVersion, session.draft.intentMonth)
            inFlight.remove(session.binding)
            if (result.isSuccess) draftStore.remove(session)
            if (session.binding != activeBinding || _state.value.session != session) return@launch
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
                    _state.update { it.copy(isSubmitting = false, session = session.copy(
                        draft = session.draft.copy(validationError = err.toUiText(R.string.error_generic)))) }
                },
            )
        }
    }

    private fun mutateDraft(transform: (IncomePlanDraftUi) -> IncomePlanDraftUi) {
        if (!_state.value.canModify || _state.value.isSubmitting || _state.value.succeeded) return
        _state.update { state ->
            val session = state.session ?: return@update state
            state.copy(session = session.copy(draft = transform(session.draft)))
        }
        _state.value.session?.let(draftStore::write)
    }
}
