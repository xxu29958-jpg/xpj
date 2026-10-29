package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.DebtWriteActions
import com.ticketbox.data.repository.DebtWriteObservation
import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.DebtCreationActions
import com.ticketbox.data.repository.DebtDraft
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.data.repository.logNetworkWarning
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
import com.ticketbox.presentation.formatMinorAmountInput
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.withContext

class DebtListViewModel(
    private val repository: DebtActions,
    private val creation: DebtCreationActions,
    private val writes: DebtWriteActions,
    private val lens: DebtListLens = DebtListLens.Ledger,
    savedStateHandle: SavedStateHandle = SavedStateHandle(),
) : ViewModel() {

    private var adjustmentBinding = writes.currentAccess()?.binding
    private var writeObservation: DebtWriteObservation? = null

    private var activeAccess = creation.currentAccess()
    private val drafts = DebtCreationDraftStore(savedStateHandle)
    private var creationDraft = activeAccess?.binding?.let(drafts::read)
        set(value) {
            field = value
            value?.let(drafts::write)
            value?.billCaptureKey?.let {
                viewModelScope.launch {
                    withContext(NonCancellable) {
                        creation.billSources?.let { drafts.persistBillDraft(it, value) }?.onFailure { error ->
                            _state.update { it.copy(error = error.toUiText(R.string.debt_bill_parse_failed)) }
                        }
                    }
                }
            }
        }
    private var draftGeneration = 0L
    private var completedIntentIds = emptySet<Long>()
    private val _state = MutableStateFlow(
        DebtListUiState(canModify = activeAccess?.canModify == true, lens = lens,
            addDraft = creationDraft?.input ?: DebtDraftUi(),
            publicationUnverified = creationDraft?.publicationAttempted == true),
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
            @OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
            creation.observeActiveLedgerAccess().flatMapLatest { access ->
                access?.binding?.let { creation.billSources?.observe(it) } ?: flowOf(emptyList())
            }.collect { inputs ->
                _state.update { it.copy(billInputs = inputs, activeBillCaptureKey = creationDraft?.billCaptureKey) }
            }
        }
        viewModelScope.launch {
            repository.observeReadAccessDenials().collect { denial ->
                if (denial.binding != creation.currentAccess()?.binding) return@collect
                loadGeneration++
                _state.update { it.copy(debts = emptyList(), fetchedAt = null, fromCache = false, isLoading = false,
                    homeCurrencyResolved = false, error = denial.failure.toUiText(R.string.debt_list_load_failed)) }
            }
        }
        viewModelScope.launch {
            repository.observeResourceDenials().collect { denial ->
                if (denial.binding != creation.currentAccess()?.binding) return@collect
                val replaceInFlightRead = _state.value.isLoading
                loadGeneration++
                _state.update { it.copy(debts = it.debts.filterNot { debt -> debt.publicId == denial.debtPublicId },
                    isLoading = false, error = denial.failure.toUiText(R.string.debt_list_load_failed)) }
                // The old response must stay retired, but unrelated debts still need their current read.
                if (replaceInFlightRead) refresh()
            }
        }
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
                    creationDraft = access?.binding?.let(drafts::read)
                    _state.value = DebtListUiState(canModify = access?.canModify == true, lens = lens,
                        addDraft = creationDraft?.input ?: DebtDraftUi(),
                        publicationUnverified = creationDraft?.publicationAttempted == true)
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
                    _state.update { it.copy(canModify = false, debts = emptyList(), fetchedAt = null,
                        fromCache = false, isLoading = false, homeCurrencyResolved = false) }
                } else if (change.binding == creation.currentAccess()?.binding) {
                    if (changedBinding || change.requiresRefresh) refresh()
                }
            }
        }
    }

    fun refresh(calendars: com.ticketbox.data.repository.LedgerCalendarReader? = null) {
        val observation = writeObservation
        if (observation?.binding == null || observation.binding != creation.currentAccess()?.binding) {
            _state.update { it.copy(isLoading = writes.currentAccess() != null) }
            return
        }
        val gen = ++loadGeneration
        val binding = observation.binding
        _state.update { it.copy(isLoading = true, error = null) }
        viewModelScope.launch {
            val calendar = calendars?.let { it.cached(binding) ?: it.refresh(binding).getOrNull() }
            val result = repository.listDebts(lens)
            // Drop a load superseded by a newer refresh (which set isLoading and owns clearing it).
            if (gen != loadGeneration || binding != creation.currentAccess()?.binding ||
                binding != writes.currentAccess()?.binding) return@launch
            result.fold(
                onSuccess = { snapshot ->
                    val page = snapshot.value
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
                    val retained = creationDraft?.captureContext(ledgerCurrency, calendar?.revision)
                        ?.also { saved -> creationDraft = saved }
                    _state.update {
                        it.copy(
                            isLoading = false,
                            canModify = creation.currentAccess()?.canModify == true,
                            debts = debts,
                            fetchedAt = snapshot.fetchedAt, fromCache = snapshot.fromCache,
                            error = null,
                            addDraft = retained?.input ?: it.addDraft,
                            homeCurrencyResolved = ledgerCurrency != null && retained?.input?.homeCurrency == ledgerCurrency,
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
        val state = _state.value
        if (state.isSubmitting || state.publicationUnverified || creation.currentAccess()?.canModify != true) return
        if (creation.currentAccess()?.binding != creationDraft?.binding) return
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
                DebtDraftField.PrincipalDate -> state.addDraft.copy(principalDate = value, validationError = null)
        }
        draftGeneration++ // A later manual edit retires an in-flight bill suggestion.
        creationDraft = creationDraft?.copy(input = updated.copy(userTouched = true))
        _state.update { it.copy(addDraft = requireNotNull(creationDraft).input, isParsingBill = false, pendingBillParsePrefill = false) }
    }

    fun openDraft(direction: String = com.ticketbox.domain.model.DebtDirections.I_OWE) {
        if (creationDraft?.hasInput == false) {
            creationDraft = creationDraft?.copy(input = _state.value.addDraft.copy(direction = direction))
            _state.update { it.copy(addDraft = requireNotNull(creationDraft).input) }
        }
    }

    fun acknowledgeCreation(billPrefill: Boolean = false) {
        _state.update { if (billPrefill) it.copy(pendingBillParsePrefill = false) else it.copy(addAccepted = false) }
    }

    fun discardDraft() {
        if (_state.value.isSubmitting || _state.value.publicationUnverified) return
        creationDraft?.billCaptureKey?.let { billTask(it, DebtBillTaskAction.Discard); return }
        creationDraft?.let(drafts::remove)
        creationDraft = activeAccess?.binding?.let { binding ->
            DebtCreationDraft(binding, input = DebtDraftUi(homeCurrency = _state.value.ledgerHomeCurrency ?: FxContract.HomeCurrency),
                currencyCaptured = _state.value.homeCurrencyResolved)
        }
        draftGeneration += 1
        _state.update {
            it.copy(
                addDraft = creationDraft?.input ?: DebtDraftUi(),
                isSubmitting = false,
                addAccepted = false,
                pendingBillParsePrefill = false,
                isParsingBill = false,
                activeBillCaptureKey = creationDraft?.billCaptureKey,
            )
        }
    }

    fun markBillParsePreparing(): DebtBillParseAttempt? {
        val current = _state.value
        val access = creation.currentAccess() ?: return null
        // homeCurrencyResolved 门与 submitDraft 对齐（PR#255 R5 P3）：币种未确认时预填必按
        // 兜底口径格式化，重绑后金额文本静默变义（JPY 账本的 "1200.00" 重绑后非法/变值）。
        if (!access.canModify || access.binding != activeAccess?.binding || !current.canPrepareBill) {
            return null
        }
        val currency = current.ledgerHomeCurrency ?: return null
        val attempt = DebtBillParseAttempt(access.binding, currency, ++draftGeneration)
        _state.update { it.copy(isParsingBill = true, error = null) }
        return attempt
    }

    fun parseDebtBillImage(attempt: DebtBillParseAttempt, image: PreparedUploadImage?, cancelled: Boolean = false) {
        if (!continueBillParse(attempt)) return
        if (image == null) {
            _state.update { it.copy(isParsingBill = false,
                error = if (cancelled) null else UiText.res(R.string.debt_bill_parse_failed)) }
            return
        }
        val sources = creation.billSources
        val original = creationDraft
        if (sources == null || original == null) {
            _state.update { it.copy(isParsingBill = false, error = UiText.res(R.string.debt_bill_parse_failed)) }
            return
        }
        val captured = original.captureBill()
        creationDraft = captured
        viewModelScope.launch {
            val input = sources.capture(attempt.binding, captured.creationKey,
                requireNotNull(captured.billCaptureKey), drafts.encode(captured), image)
            // capture inserts the durable input; edits made while that insert was pending must follow it.
            val accepted = input.fold(onSuccess = { stored -> drafts.persistBillDraft(sources, captured).map { stored } },
                onFailure = { Result.failure(it) })
            if (!continueBillParse(attempt)) return@launch
            _state.update { it.copy(isParsingBill = false, pendingBillParsePrefill = true,
                activeBillCaptureKey = captured.billCaptureKey,
                billInputs = accepted.getOrNull()?.let { row -> it.billInputs.filterNot { old -> old.captureKey == row.captureKey } + row }
                    ?: it.billInputs,
                error = accepted.exceptionOrNull()?.toUiText(R.string.debt_bill_parse_failed)) }
            if (accepted.isFailure) return@launch
            val delivered = sources.observe(attempt.binding).first { rows -> rows.any {
                it.captureKey == captured.billCaptureKey && (it.source != null || it.command?.status in setOf(
                    com.ticketbox.data.local.PendingMutationStatus.Done, com.ticketbox.data.local.PendingMutationStatus.Failed,
                    com.ticketbox.data.local.PendingMutationStatus.Conflict))
            } }.single { it.captureKey == captured.billCaptureKey }
            if (continueBillParse(attempt, requireBusy = false) && !delivered.needsAttention) {
                billTask(delivered.captureKey, DebtBillTaskAction.Parse)
            }
        }
    }

    private fun continueBillParse(attempt: DebtBillParseAttempt, requireBusy: Boolean = true): Boolean {
        val current = _state.value
        if (attempt.generation != draftGeneration || (requireBusy && !current.isParsingBill)) return false
        val access = creation.currentAccess()
        if (access != null && access.binding == attempt.binding && access.canModify &&
            current.ledgerHomeCurrency == attempt.homeCurrency) {
            return true
        }
        _state.update { it.copy(isParsingBill = false) }
        return false
    }

    fun billTask(captureKey: String, action: DebtBillTaskAction) {
        val sources = creation.billSources ?: return
        val binding = creation.currentAccess()?.binding ?: return
        if (!_state.value.acceptsBillTask(action)) return
        val generation = ++draftGeneration
        _state.update { it.copy(isParsingBill = action == DebtBillTaskAction.Parse, error = null) }
        viewModelScope.launch {
            val result = try {
                val input = sources.find(binding, captureKey).getOrThrow()
                if (generation != draftGeneration || binding != creation.currentAccess()?.binding) return@launch
                if (action == DebtBillTaskAction.Resume) {
                    creationDraft = drafts.resume(requireNotNull(input), creationDraft)
                    _state.update { it.copy(addDraft = requireNotNull(creationDraft).input, activeBillCaptureKey = captureKey,
                        pendingBillParsePrefill = true, publicationUnverified = creationDraft?.publicationAttempted == true) }
                }
                runDebtBillTask(sources, input, action)
            } catch (cancelled: kotlinx.coroutines.CancellationException) {
                throw cancelled
            } catch (error: Exception) { Result.failure(debtBillTaskFailure(error)) }
            if (generation != draftGeneration || binding != creation.currentAccess()?.binding) return@launch
            val completed = result.getOrNull()
            val adopted = completed?.source?.adoptedDebtPublicId != null
            val filled = completed?.prefill(_state.value)
            if (filled != null) creationDraft = creationDraft?.copy(input = filled)
            if (completed?.ends(creationDraft, captureKey) == true) {
                creationDraft = creationDraft?.copy(billCaptureKey = null, publicationAttempted = false)
                _state.update { it.copy(publicationUnverified = false) }
                discardDraft()
                if (adopted) refresh()
            }
            _state.update { it.afterBillTask(result, creationDraft?.input) }
        }
    }

    fun submitDraft() {
        val state = _state.value
        val access = creation.currentAccess() ?: return
        val original = creationDraft ?: return
        if (!state.canSubmitCreation || !access.canModify) return
        if (access.binding != original.binding) return
        val currency = state.ledgerHomeCurrency ?: return
        val draft = if (original.publicationAttempted) original.input else state.addDraft.withInheritedModelFrom(state.debts)
        val validation = draft.validationMessage
        if (validation != null) {
            _state.update {
                it.copy(addDraft = it.addDraft.copy(validationError = UiText.res(validation)))
            }
            return
        }
        val request = draft.toCreationDraft(requireNotNull(draft.parsedAmountCents())).copy(
            billSource = original.sourceReference(state),
        )
        val submitted = original.copy(input = draft, frozenBillSource = request.billSource)
        creationDraft = submitted.copy(publicationAttempted = true)
        _state.update { it.copy(isSubmitting = true, publicationUnverified = true, addAccepted = false, flashMessage = null) }
        viewModelScope.launch {
            val result = drafts.persistBillDraft(creation.billSources, submitted).fold(
                onSuccess = { creation.createDebt(original.binding, request, currency, original.creationKey) },
                onFailure = { Result.failure(it) },
            )
            val retained = drafts.settle(original) { submitted.afterPublication(result) } ?: return@launch
            if (creationDraft?.creationKey != original.creationKey || creation.currentAccess()?.binding != original.binding) return@launch
            val accepted = retained.creationKey != original.creationKey
            creationDraft = retained
            _state.update { it.copy(isSubmitting = false, publicationUnverified = retained.publicationAttempted,
                addDraft = retained.input, addAccepted = accepted, activeBillCaptureKey = retained.billCaptureKey,
                flashMessage = if (accepted) UiText.res(R.string.debt_create_local_saved) else null) }
            if (accepted) refresh()
        }
    }

    fun dismissFlash() {
        _state.update { it.copy(flashMessage = null, billPreview = null) }
    }
}

private fun debtBillTaskFailure(error: Exception): RepositoryException {
    if (error is RepositoryException) return error
    logNetworkWarning("operation=Debt bill task unverified", error)
    return RepositoryException("Debt bill draft is unreadable",
        localFailure = com.ticketbox.data.repository.LocalRepositoryFailure.DebtBillDraftUnreadable, cause = error)
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
    timeInput = principalDate.takeIf(String::isNotBlank)?.let {
        com.ticketbox.domain.model.ExpenseTimeInput(precision = "date_only",
            userLocalDate = it, calendarRevision = requireNotNull(calendarRevision))
    },
)

internal fun DebtDraftUi.prefillFrom(suggestion: DebtBillSuggestion): DebtDraftUi {
    val parsedInstallmentCount = suggestion.installmentCount?.toIntOrNullIn(1, 600)
    val parsedInstallmentPeriod = suggestion.installmentPeriodMonths?.toIntOrNullIn(1, 120)
    return copy(
        counterpartyLabel = counterpartyLabel.ifBlank { suggestion.merchant?.trim().orEmpty() },
        // R8-2：provider 声明金额单位为 **CNY 分**（debt_bill_parse_service prompt：两位小数
        // 分单位，mock ¥1,200.00→120000）。草稿绑定非 CNY（JPY/KRW 零小数账本）时预填会把
        // 分当账本 minor 提交（100×）→ 金额字段不预填、留用户手填（其它字段保留预填）；
        // 不做换算（无 FX 路径，换算属新设计）。CNY 账本维持原口径（零小数 home 不 ÷100）。
        amountYuanInput = amountYuanInput.ifBlank { suggestion.principalAmountCents
            ?.takeIf { homeCurrency == CurrencyCode.CNY }
            ?.let { formatMinorAmountInput(it, homeCurrency) }
            .orEmpty() },
        kind = if (kind == DebtKinds.UNSPECIFIED && parsedInstallmentCount != null) DebtKinds.INSTALLMENT else kind,
        installmentCountInput = installmentCountInput.ifBlank { parsedInstallmentCount?.toString().orEmpty() },
        installmentPeriodInput = installmentPeriodInput.ifBlank { parsedInstallmentPeriod?.toString().orEmpty() },
        validationError = null,
    )
}

/** Initial capability capture only; an already bound original never reinterprets its amount. */
internal fun DebtDraftUi.rebindHomeCurrency(authoritative: CurrencyCode): DebtDraftUi {
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

internal fun DebtDraftUi.withInheritedModelFrom(debts: List<Debt>): DebtDraftUi {
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
