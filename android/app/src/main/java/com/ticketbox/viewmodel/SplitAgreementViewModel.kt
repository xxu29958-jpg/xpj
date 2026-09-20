package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.remote.dto.BillSplitAgreementDto
import com.ticketbox.data.remote.dto.BillSplitChangeAcceptRequestDto
import com.ticketbox.data.remote.dto.BillSplitChangeCreateRequestDto
import com.ticketbox.data.repository.DebtTask
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.SplitAgreementActions
import com.ticketbox.data.repository.SplitAgreementPayload
import com.ticketbox.data.repository.SPLIT_ACCEPT
import com.ticketbox.data.repository.SPLIT_CREATE
import com.ticketbox.data.repository.SPLIT_REJECT
import com.ticketbox.data.repository.SPLIT_WITHDRAW
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.ui.components.formatAmountInput
import com.ticketbox.ui.components.parseAmountCents
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class SplitAgreementUiState(
    val task: DebtTask? = null,
    val agreement: BillSplitAgreementDto? = null,
    val shareInput: String = "",
    val settlementInput: String = "",
    val reason: String = "",
    val settlementEdited: Boolean = false,
    val confirmed: Boolean = false,
    val previewReady: Boolean = false,
    val loading: Boolean = false,
    val submitting: Boolean = false,
    val error: String? = null,
    val message: String? = null,
    val rows: List<OutboxRow> = emptyList(),
    val intents: Map<Long, SplitAgreementPayload> = emptyMap(),
    val acknowledgedRevision: Long = 0,
) {
    val busy: Boolean get() = submitting || rows.any { it.status != PendingMutationStatus.Done }
    val canPropose: Boolean get() = agreement?.viewerIsParty == true && agreement.pendingProposal == null &&
        agreement.pendingRepaymentDebtPublicIds.isEmpty() && previewReady && confirmed && !busy && !loading
}

/** Drafts are scoped to the entire logical task, including origin, principal and binding generation. */
class SplitAgreementViewModel(private val repository: SplitAgreementActions) : ViewModel() {
    private val _state = MutableStateFlow(SplitAgreementUiState())
    val state = _state.asStateFlow()
    private val retained = mutableMapOf<DebtTask, SplitAgreementUiState>()
    private var queryGeneration = 0L
    private var observation: Job? = null
    private var observedTask: DebtTask? = null
    private val completedIds = mutableSetOf<Pair<DebtTask, Long>>()

    fun load(task: DebtTask?) {
        if (_state.value.task != task) {
            _state.value.task?.let { retained[it] = _state.value.copy(submitting = false, loading = false) }
            observation?.cancel()
            observedTask = null
            queryGeneration++
            _state.value = task?.let { retained[it] ?: SplitAgreementUiState(task = it) } ?: SplitAgreementUiState()
        }
        if (task != null) {
            observeOriginal(task)
            refresh()
        }
    }

    fun editShare(value: String) {
        queryGeneration++
        _state.update { it.copy(shareInput = value, settlementEdited = false, previewReady = false, confirmed = false, loading = false) }
    }
    fun editSettlement(value: String) = _state.update { it.copy(settlementInput = value, settlementEdited = true, confirmed = false) }
    fun editReason(value: String) = _state.update { it.copy(reason = value, confirmed = false) }
    fun confirm(value: Boolean) = _state.update { it.copy(confirmed = value) }

    fun refresh() {
        val current = _state.value
        val task = current.task ?: return
        val currency = current.agreement?.homeCurrencyCode?.let(CurrencyCode::fromStorageKeyOrNull)
        val share = if (current.shareInput.isBlank()) null else currency?.let { parseAmountCents(current.shareInput, it) }
        if (current.shareInput.isNotBlank() && share == null) {
            _state.update { it.copy(error = "请填写有效的新份额。", previewReady = false) }
            return
        }
        val request = ++queryGeneration
        _state.update { it.copy(loading = true, error = null, previewReady = false, confirmed = false) }
        viewModelScope.launch {
            val result = repository.load(task, share)
            if (request != queryGeneration || _state.value.task != task) return@launch
            result.fold(onSuccess = { agreement ->
                val code = CurrencyCode.fromStorageKeyOrNull(agreement.homeCurrencyCode)
                _state.update { it.copy(agreement = agreement, loading = false,
                    shareInput = code?.let { c -> formatAmountInput(agreement.preview.newShareAmountCents, c) }.orEmpty(),
                    settlementInput = if (it.settlementEdited) it.settlementInput else
                        code?.let { c -> formatAmountInput(agreement.preview.defaultSettlementNetAmountCents, c) }.orEmpty(),
                    previewReady = code != null) }
                observeOriginal(task.copy(debtPublicId = agreement.originalDebt.publicId))
            }, onFailure = {
                _state.update { it.copy(loading = false, error = "新约定暂时无法读取，请重试。") }
            })
        }
    }

    private fun observeOriginal(original: DebtTask) {
        if (observedTask == original) return
        observation?.cancel()
        observedTask = original
        observation = viewModelScope.launch {
            repository.observe(original).collect { rows ->
                if (observedTask != original || _state.value.task?.binding != original.binding) return@collect
                val completed = rows.filter { it.status == PendingMutationStatus.Done }
                val fresh = completed.filter { completedIds.add(original.copy(debtPublicId = it.targetId.removePrefix("debt:")) to it.id) }
                _state.update { it.copy(rows = rows, intents = rows.mapNotNull { row -> repository.describe(row)?.let { row.id to it } }.toMap(), message = splitSubmissionMessage(rows),
                    acknowledgedRevision = it.acknowledgedRevision + fresh.size) }
                if (fresh.isNotEmpty()) refresh()
            }
        }
    }

    fun propose() {
        val state = _state.value
        val agreement = state.agreement ?: return
        if (!state.canPropose) return
        val currency = CurrencyCode.fromStorageKeyOrNull(agreement.homeCurrencyCode) ?: return
        val share = parseAmountCents(state.shareInput, currency) ?: return
        val settlement = parseSplitSettlement(state.settlementInput, currency)
        val reason = state.reason.trim()
        if (settlement == null || reason.isBlank() || reason.codePointCount(0, reason.length) > 500) {
            _state.update { it.copy(error = "请填写有效结算金额和不超过 500 字的原因。") }
            return
        }
        submit(SplitAgreementPayload(operation = SPLIT_CREATE, originalDebtPublicId = agreement.originalDebt.publicId,
            returnDebtPublicId = agreement.returnDebt?.publicId, create = BillSplitChangeCreateRequestDto(share, settlement, reason,
                agreement.originalDebt.rowVersion, agreement.returnDebt?.rowVersion)))
    }

    fun resolve(accept: Boolean) {
        val state = _state.value
        val agreement = state.agreement ?: return
        val proposal = agreement.pendingProposal ?: return
        if (!agreement.viewerIsParty || state.busy || state.loading) return
        if (accept && (!state.confirmed || proposal.proposedByYou || !state.previewReady ||
                agreement.pendingRepaymentDebtPublicIds.isNotEmpty())) return
        val operation = if (accept) SPLIT_ACCEPT else if (proposal.proposedByYou) SPLIT_WITHDRAW else SPLIT_REJECT
        submit(SplitAgreementPayload(operation = operation, originalDebtPublicId = agreement.originalDebt.publicId,
            proposalPublicId = proposal.publicId, returnDebtPublicId = agreement.returnDebt?.publicId, accept = if (accept) BillSplitChangeAcceptRequestDto(
                agreement.originalDebt.rowVersion, agreement.returnDebt?.rowVersion) else null))
    }

    private fun submit(intent: SplitAgreementPayload) {
        val task = _state.value.task ?: return
        if (_state.value.busy) return
        _state.update { it.copy(submitting = true, error = null) }
        viewModelScope.launch {
            val result = repository.submit(task.copy(debtPublicId = intent.originalDebtPublicId), intent)
            if (_state.value.task != task) return@launch
            result.fold(onSuccess = {
                _state.update { it.copy(submitting = false, confirmed = false, message = "原提交已保存，等待同步。") }
            }, onFailure = {
                _state.update { it.copy(submitting = false, error = "原提交未保存，请核对连接与待处理提交后重试。") }
            })
        }
    }

    fun recover(row: OutboxRow, drop: Boolean) {
        val state = _state.value
        val task = state.task ?: return
        if (state.submitting || state.rows.none { it == row }) return
        val intent = state.intents[row.id]
        val draft = if (drop) restorableCreateDraft(state, intent) else null
        if (drop && intent?.operation == SPLIT_CREATE && draft == null) {
            _state.update { it.copy(error = "原提交内容无法确认，请保留记录并重新核对。") }
            return
        }
        val original = intent?.originalDebtPublicId ?: row.targetId.removePrefix("debt:")
        _state.update { it.copy(submitting = true, error = null) }
        viewModelScope.launch {
            val result = repository.recover(task.copy(debtPublicId = original), row, drop)
            if (_state.value.task != task) return@launch
            result.fold(onSuccess = {
                _state.update { current -> draft?.let { (share, settlement, reason) ->
                    current.copy(shareInput = share, settlementInput = settlement, reason = reason,
                        settlementEdited = true, confirmed = false, submitting = false)
                } ?: current.copy(submitting = false) }
                if (drop) refresh()
            }, onFailure = {
                _state.update { it.copy(submitting = false, error = "原提交状态已变化，请重新核对。") }
            })
        }
    }
}

private fun restorableCreateDraft(
    state: SplitAgreementUiState,
    intent: SplitAgreementPayload?,
): Triple<String, String, String>? {
    val create = intent?.takeIf { it.operation == SPLIT_CREATE }?.create ?: return null
    val currency = state.agreement?.homeCurrencyCode?.let(CurrencyCode::fromStorageKeyOrNull) ?: return null
    return Triple(formatAmountInput(create.newShareAmountCents, currency),
        formatAmountInput(create.settlementNetAmountCents, currency), create.reason)
}

internal fun parseSplitSettlement(value: String, currency: CurrencyCode): Long? {
    val cleaned = value.trim()
    val negative = cleaned.startsWith("-")
    val magnitude = parseAmountCents(if (negative) cleaned.drop(1) else cleaned, currency) ?: return null
    return if (negative) -magnitude else magnitude
}

private fun splitSubmissionMessage(rows: List<OutboxRow>): String? = when {
    rows.any { it.status != PendingMutationStatus.Done } -> "原提交已保存，等待同步或核对。"
    rows.any { it.status == PendingMutationStatus.Done } -> "原提交已由服务端接收。"
    else -> null
}
