package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.DebtWriteActions
import com.ticketbox.data.repository.DebtWriteObservation
import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.DebtCreationActions
import com.ticketbox.data.repository.DebtDraft
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtBillSuggestion
import com.ticketbox.domain.model.DebtCounterpartyTypes
import com.ticketbox.domain.model.DebtKinds
import com.ticketbox.domain.model.DebtListLens
import com.ticketbox.domain.model.DebtSourceTypes
import com.ticketbox.domain.model.FxContract
import com.ticketbox.domain.model.UiText
import com.ticketbox.upload.PreparedUploadImage
import com.ticketbox.ui.components.formatMinorAmountInput
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

class DebtListViewModel(
    private val repository: DebtActions,
    private val creation: DebtCreationActions,
    private val writes: DebtWriteActions,
    private val lens: DebtListLens = DebtListLens.Ledger,
) : ViewModel() {

    private var adjustmentBinding = writes.currentAccess()?.binding
    private var writeObservation: DebtWriteObservation? = null

    private var activeAccess = creation.currentAccess()
    private var draftGeneration = 0L
    private var completedIntentIds = emptySet<Long>()
    private val _state = MutableStateFlow(
        DebtListUiState(canModify = activeAccess?.canModify == true, lens = lens),
    )
    val state: StateFlow<DebtListUiState> = _state.asStateFlow()

    // Monotonic load token (mirrors DebtGoalViewModel): a refresh applies its result only if it is
    // still the latest. Overlapping refreshes — init + reload on overlay (re-)entry + the refresh
    // after a create — each bump it, so a slow earlier list fetch can't overwrite newer data (the
    // just-created debt, or a switched ledger's debts). Every bump is a refresh, so a superseded
    // load is always replaced by a newer refresh that owns the loading flag — it just drops.
    private var loadGeneration = 0L

    init {
        viewModelScope.launch {
            combine(
                creation.observeActiveLedgerAccess(),
                creation.observePendingCreations(),
            ) { access, snapshot -> access to snapshot }.collect { (access, snapshot) ->
                if (access != creation.currentAccess()) return@collect
                val bindingChanged = access?.binding != activeAccess?.binding
                activeAccess = access
                if (bindingChanged) {
                    draftGeneration += 1
                    completedIntentIds = emptySet()
                    _state.value = DebtListUiState(canModify = access?.canModify == true, lens = lens)
                    refresh()
                } else {
                    _state.update { it.copy(canModify = access?.canModify == true,
                        isParsingBill = it.isParsingBill && access?.canModify == true) }
                }
                // Keep the latest queue snapshot until its matching access arrives, in either order.
                if (snapshot.binding != access?.binding) return@collect
                val newlyCompleted = snapshot.completedIntentIds - completedIntentIds
                completedIntentIds = completedIntentIds + snapshot.completedIntentIds
                _state.update {
                    it.copy(
                        pendingCreations = snapshot.intents,
                        creationSettlementRevision = it.creationSettlementRevision +
                            if (newlyCompleted.isNotEmpty()) 1 else 0,
                    )
                }
                if (newlyCompleted.isNotEmpty()) refresh()
            }
        }
        viewModelScope.launch {
            writes.observeWrites().collect { change ->
                val changedBinding = adjustmentBinding != change.binding
                adjustmentBinding = change.binding
                writeObservation = change
                if (change.binding == null) {
                    loadGeneration++
                    _state.value = DebtListUiState(canModify = false, lens = lens)
                } else if (change.binding == creation.currentAccess()?.binding) {
                    if (changedBinding) reload() else if (change.requiresRefresh) refresh()
                }
            }
        }
    }

    /**
     * 进入 overlay 时调用：先清掉上一账本残留的欠款再拉，避免在新账本下短暂看到旧账本的欠款
     * （账本隔离；overlay VM 跨账本切换存活，见 DebtGoalViewModel.refresh(clearStale = true)）。
     * 草稿一并重置：旧账本草稿文本若存活到新账本，响应落地时会被 rebind 静默重解释
     * （JPY 账本的 "1200" 落到 CNY 账本变 120000 minor，100× —— PR#255 R5 P2）；与
     * 打开新建抽屉必先 [resetDraft] 同一语义。
     */
    fun reload() {
        // Re-entering the same ledger cannot discard a publication awaiting Room acknowledgement.
        if (_state.value.isSubmitting) {
            refresh()
            return
        }
        draftGeneration += 1
        _state.update {
            it.copy(
                debts = emptyList(),
                error = null,
                canModify = creation.currentAccess()?.canModify == true,
                addAccepted = false,
                flashMessage = null,
                // 新账本币种未知，创建重新禁用到本次拉取成功（PR#255 P1-3）。
                homeCurrencyResolved = false,
                ledgerHomeCurrency = null,
                // 账本切换即作废旧账本草稿：币种重绑前的兜底口径文本不得跨账本存活（PR#255 R5 P2）。
                addDraft = DebtDraftUi(),
                isParsingBill = false,
            )
        }
        refresh()
    }

    fun refresh() {
        val observation = writeObservation
        if (observation?.binding == null || observation.binding != creation.currentAccess()?.binding) {
            _state.update { it.copy(isLoading = writes.currentAccess() != null) }
            return
        }
        val gen = ++loadGeneration
        val binding = creation.currentAccess()?.binding
        _state.update { it.copy(isLoading = true, error = null) }
        viewModelScope.launch {
            val result = repository.listDebts(lens)
            // Drop a load superseded by a newer refresh (which set isLoading and owns clearing it).
            if (gen != loadGeneration || binding != creation.currentAccess()?.binding ||
                binding != writes.currentAccess()?.binding) return@launch
            result.fold(
                onSuccess = { page ->
                    if (!page.debts.filterNot { "debt:${it.publicId}" in observation.unresolvedTargetIds }
                            .all(observation::acceptsCanonical)) {
                        _state.update { it.copy(isLoading = false,
                            error = UiText.res(R.string.debt_write_canonical_refresh_required)) }
                        return@launch
                    }
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
                            canModify = creation.currentAccess()?.canModify == true,
                            debts = debts,
                            error = null,
                            addDraft = if (it.isSubmitting) it.addDraft else {
                                ledgerCurrency?.let(it.addDraft::rebindHomeCurrency) ?: it.addDraft
                            },
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
            if (state.isSubmitting) return@update state
            val updated = when (field) {
                DebtDraftField.Direction -> state.addDraft.copy(direction = value, validationError = null)
                DebtDraftField.Counterparty -> state.addDraft
                    .copy(counterpartyLabel = value, validationError = null)
                    .withInheritedModelFrom(state.debts)
                DebtDraftField.Amount -> state.addDraft.copy(amountYuanInput = value, validationError = null)
                DebtDraftField.Note -> state.addDraft.copy(note = value, validationError = null)
                DebtDraftField.Kind -> state.addDraft.copy(kind = value, validationError = null)
                DebtDraftField.InstallmentCount -> state.addDraft.copy(installmentCountInput = value, validationError = null)
                DebtDraftField.InstallmentPeriod -> state.addDraft.copy(installmentPeriodInput = value, validationError = null)
            }
            state.copy(addDraft = updated.copy(userTouched = true))
        }
    }

    fun resetDraft() {
        if (_state.value.isSubmitting) return
        draftGeneration += 1
        _state.update {
            it.copy(
                addDraft = DebtDraftUi(homeCurrency = it.ledgerHomeCurrency ?: FxContract.HomeCurrency),
                isSubmitting = false,
                addAccepted = false,
                pendingBillParsePrefill = false,
                isParsingBill = false,
            )
        }
    }

    fun markBillParsePreparing(): DebtBillParseAttempt? {
        val current = _state.value
        val access = creation.currentAccess() ?: return null
        // homeCurrencyResolved 门与 submitDraft 对齐（PR#255 R5 P3）：币种未确认时预填必按
        // 兜底口径格式化，重绑后金额文本静默变义（JPY 账本的 "1200.00" 重绑后非法/变值）。
        if (!access.canModify || access.binding != activeAccess?.binding || current.isParsingBill ||
            current.isSubmitting || !current.homeCurrencyResolved) {
            return null
        }
        val currency = current.ledgerHomeCurrency ?: return null
        val attempt = DebtBillParseAttempt(access.binding, currency, ++draftGeneration)
        _state.update { it.copy(isParsingBill = true, error = null) }
        return attempt
    }

    fun parseDebtBillImage(attempt: DebtBillParseAttempt, image: PreparedUploadImage?) {
        if (!continueBillParse(attempt)) return
        if (image == null) {
            _state.update { it.copy(isParsingBill = false, error = UiText.res(R.string.debt_bill_parse_failed)) }
            return
        }
        viewModelScope.launch {
            val result = repository.parseDebtBillImage(attempt.binding, image.fileName, image.contentType, image.bytes)
            if (!continueBillParse(attempt)) return@launch
            result.fold(
                onSuccess = { suggestion ->
                    val filled = DebtDraftUi(homeCurrency = attempt.homeCurrency)
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

    private fun continueBillParse(attempt: DebtBillParseAttempt): Boolean {
        val current = _state.value
        if (attempt.generation != draftGeneration || !current.isParsingBill) return false
        val access = creation.currentAccess()
        if (access != null && access.binding == attempt.binding && access.canModify &&
            current.ledgerHomeCurrency == attempt.homeCurrency) {
            return true
        }
        _state.update { it.copy(isParsingBill = false) }
        return false
    }

    fun ackBillParsePrefill() {
        _state.update { it.copy(pendingBillParsePrefill = false) }
    }

    fun submitDraft() {
        val state = _state.value
        val access = creation.currentAccess() ?: return
        if (state.isSubmitting || state.isParsingBill || !access.canModify || !state.homeCurrencyResolved) return
        if (access.binding != activeAccess?.binding) return
        val currency = state.ledgerHomeCurrency ?: return
        val draft = state.addDraft.withInheritedModelFrom(state.debts)
        val amount = draft.parsedAmountCents()
        val validation = when {
            draft.noteTooLong -> R.string.debt_context_too_long
            draft.counterpartyLabel.isBlank() || amount == null -> R.string.debt_create_validation_error
            else -> null
        }
        if (validation != null) {
            _state.update {
                it.copy(addDraft = it.addDraft.copy(validationError = UiText.res(validation)))
            }
            return
        }
        val request = draft.toCreationDraft(requireNotNull(amount))
        publishDraft(request, access.binding, currency)
    }

    private fun publishDraft(request: DebtDraft, binding: LogicalSessionBinding, currency: CurrencyCode) {
        val gen = draftGeneration
        _state.update { it.copy(isSubmitting = true, addAccepted = false, flashMessage = null) }
        viewModelScope.launch {
            val result = creation.createDebt(binding, request, currency)
            if (gen != draftGeneration || binding != creation.currentAccess()?.binding) return@launch
            result.fold(
                onSuccess = {
                    _state.update {
                        it.copy(
                            isSubmitting = false,
                            addDraft = DebtDraftUi(homeCurrency = it.ledgerHomeCurrency ?: FxContract.HomeCurrency),
                            flashMessage = UiText.res(R.string.debt_create_local_saved),
                            addAccepted = true,
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

private fun DebtDraftUi.toCreationDraft(amount: Long): DebtDraft = DebtDraft(
    direction = direction,
    counterpartyLabel = counterpartyLabel.trim(),
    note = note,
    principalAmountCents = amount,
    debtKind = kind,
    installmentCount = parsedInstallmentCount(),
    installmentPeriodMonths = parsedInstallmentPeriod(),
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
