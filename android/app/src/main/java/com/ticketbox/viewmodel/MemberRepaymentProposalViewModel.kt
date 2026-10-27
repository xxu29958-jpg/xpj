package com.ticketbox.viewmodel

import androidx.annotation.StringRes
import androidx.lifecycle.ViewModel
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.viewModelScope
import com.squareup.moshi.JsonClass
import com.ticketbox.R
import com.ticketbox.data.repository.DebtProposalActions
import com.ticketbox.data.repository.DebtTask
import com.ticketbox.data.repository.MemberSettlementCommand
import com.ticketbox.data.repository.MemberSettlementResult
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.MemberProposalStatuses
import com.ticketbox.domain.model.MemberRepaymentProposal
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.presentation.formatMinorAmountInput
import com.ticketbox.presentation.parseAmountCents
import com.ticketbox.viewmodel.ExpenseTimeForm
import java.time.Clock
import java.time.ZoneId
import java.util.UUID
import kotlinx.coroutines.Job
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class MemberProposalUiState(
    /** Accepted proposal changes also invalidate history when the Debt rowVersion is unchanged. */
    val acknowledgedCommandRevision: Long = 0,
    val task: DebtTask? = null,
    val isLoading: Boolean = false,
    val canModify: Boolean = false,
    val proposals: List<MemberRepaymentProposal> = emptyList(),
    val error: UiText? = null,
    val errorTone: MessageTone = MessageTone.Danger,
    val activeForm: ProposalForm? = null,
    val retainedForm: ProposalForm? = null,
    val targetProposalPublicId: String? = null,
    val formCurrencyCode: String? = null,
    val formRowVersion: Long? = null,
    val formProposedAmount: Long? = null,
    val originalAttempt: MemberSettlementAttempt? = null,
    val originalContext: MemberSettlementContext? = null,
    val amountInput: String = "",
    val noteInput: String = "",
    val paymentTime: ExpenseTimeForm? = null,
    val validationError: UiText? = null,
    val isSubmitting: Boolean = false,
    val flashMessage: UiText? = null,
    val committedDebt: Debt? = null,
) {
    val canStartCommand: Boolean get() = canModify && !isSubmitting && originalAttempt == null
    val inputsEnabled: Boolean get() = !isSubmitting && originalAttempt == null
    val submitLabelRes: Int get() = when {
        isSubmitting -> R.string.debt_action_submitting
        originalAttempt?.rejected == true -> R.string.debt_proposal_review_rejected
        originalAttempt != null -> R.string.debt_proposal_retry_original
        activeForm == ProposalForm.Propose -> R.string.debt_proposal_propose_action
        else -> R.string.debt_proposal_confirm_submit
    }
    /** The detail and its primary action use the same readable proposal state. */
    val hasReadableProposalState: Boolean
        get() = proposals.isNotEmpty() || (!isLoading && (error == null || committedDebt != null))

    /** 唯一的待确认 proposal（§3.2 一债一待确认），没有则为 null。 */
    val pendingProposal: MemberRepaymentProposal? get() = proposals.firstOrNull { it.isPending }

    /** 最近一笔已解决的 proposal（proposals 后端按 created_at 倒序返回，故首个非 pending 即最近解决）。 */
    val latestResolvedProposal: MemberRepaymentProposal? get() = proposals.firstOrNull { !it.isPending }

    /**
     * 8e §1.4 债务人 post-reject：当前无在途 proposal 且最近一笔已解决是 rejected（「金额对不上」）时，
     * 债务人卡顶显示一条 neutral 重发提示（描述对方动作 + 邀请重试，不指责债务人填错）。
     */
    val showDebtorAfterReject: Boolean
        get() = pendingProposal == null && latestResolvedProposal?.status == MemberProposalStatuses.REJECTED
}

@JsonClass(generateAdapter = false)
enum class ProposalForm { Propose, Confirm }

/** Owns the current editing task and online attempt; the server owns proposals and committed folds. */
class MemberRepaymentProposalViewModel(
    private val repository: DebtProposalActions,
    savedStateHandle: SavedStateHandle = SavedStateHandle(),
    private val clock: Clock = Clock.systemDefaultZone(),
) : ViewModel() {
    private val drafts = MemberSettlementDraftStore(savedStateHandle)
    private val _state = MutableStateFlow(MemberProposalUiState())
    val state: StateFlow<MemberProposalUiState> = _state.asStateFlow()
    private var readJob: Job? = null
    private var commandJob: Job? = null

    init {
        viewModelScope.launch {
            repository.observeAccess().collect {
                val access = repository.currentAccess()
                if (_state.value.task?.binding != null && _state.value.task?.binding != access?.binding) {
                    readJob?.cancel()
                    commandJob?.cancel()
                    _state.value = MemberProposalUiState()
                }
                _state.update { state -> state.copy(canModify = access?.canModify == true) }
            }
        }
    }

    private fun matches(task: DebtTask): Boolean =
        _state.value.task == task && repository.currentAccess()?.binding == task.binding

    fun load(task: DebtTask, readProposals: Boolean = true, debt: Debt? = null) {
        val access = repository.currentAccess() ?: return
        if (access.binding != task.binding) return
        if (_state.value.task != task) {
            readJob?.cancel()
            commandJob?.cancel()
            _state.value = (drafts.read(task) ?: MemberProposalUiState(task = task)).copy(canModify = access.canModify)
        }
        if (debt?.publicId == task.debtPublicId && _state.value.originalAttempt == null && _state.value.retainedForm == null) {
            _state.update { it.copy(originalContext = MemberSettlementContext(debt.counterpartyLabel, debt.viewerIsDebtor)) }
        }
        if (readProposals) refresh()
    }

    fun refresh() {
        if (_state.value.isSubmitting) return
        _state.value.task?.takeIf(::matches)?.let { reload(it) }
    }

    private fun reload(task: DebtTask, acknowledged: Boolean = false) {
        readJob?.cancel()
        _state.update { it.copy(isLoading = true, error = null) }
        readJob = viewModelScope.launch {
            val result = repository.listRepaymentProposals(task)
            currentCoroutineContext().ensureActive()
            if (!matches(task)) return@launch
            _state.update { current -> current.copy(
                isLoading = false,
                proposals = result.getOrNull() ?: current.proposals,
                error = result.exceptionOrNull()?.let { error ->
                    if (acknowledged) UiText.res(R.string.debt_proposal_refresh_after_action_failed)
                    else error.toUiText(R.string.debt_proposal_load_failed)
                },
                errorTone = if (acknowledged) MessageTone.Info else MessageTone.Danger,
            ) }
        }
    }

    fun openForm(task: DebtTask, form: ProposalForm, proposal: MemberRepaymentProposal? = null, debt: Debt? = null) {
        if (!matches(task) || _state.value.isSubmitting || repository.currentAccess()?.canModify != true) return
        val current = _state.value
        if (current.originalAttempt != null || current.retainedForm != null) {
            _state.update { it.copy(activeForm = it.retainedForm,
                paymentTime = it.paymentTime ?: if (it.originalAttempt == null) initialPaymentTime(form, proposal, debt, clock) else null) }
            drafts.write(_state.value)
            return
        }
        _state.update { it.copy(activeForm = form, retainedForm = form, targetProposalPublicId = proposal?.publicId,
            formCurrencyCode = debt?.homeCurrencyCode ?: proposal?.homeCurrencyCode, formRowVersion = debt?.rowVersion,
            originalContext = debt?.let { target -> MemberSettlementContext(target.counterpartyLabel, target.viewerIsDebtor) } ?: it.originalContext,
            formProposedAmount = proposal?.proposedAmountCents,
            amountInput = proposal?.let { row -> CurrencyCode.fromStorageKeyOrNull(row.homeCurrencyCode)
                ?.let { currency -> formatMinorAmountInput(row.proposedAmountCents, currency) } }.orEmpty(),
            noteInput = "", paymentTime = initialPaymentTime(form, proposal, debt, clock), validationError = null) }
        drafts.write(_state.value)
    }

    fun updateAmount(task: DebtTask, value: String) {
        if (matches(task) && !_state.value.isSubmitting && _state.value.originalAttempt == null) {
            _state.update { it.copy(amountInput = value, validationError = null) }
            drafts.write(_state.value)
        }
    }

    fun updateNote(task: DebtTask, value: String) {
        if (matches(task) && !_state.value.isSubmitting && _state.value.originalAttempt == null) {
            _state.update { it.copy(noteInput = value, validationError = null) }
            drafts.write(_state.value)
        }
    }

    fun dismissForm(task: DebtTask) {
        if (matches(task) && !_state.value.isSubmitting) _state.update {
            it.copy(activeForm = null, validationError = null)
        }
    }

    fun updatePaymentDate(task: DebtTask, value: String) {
        if (!matches(task) || !_state.value.inputsEnabled || _state.value.activeForm != ProposalForm.Propose) return
        _state.update { it.copy(paymentTime = it.paymentTime?.copy(date = value, changed = true), validationError = null) }
        drafts.write(_state.value)
    }

    fun discardDraft(task: DebtTask) {
        if (!matches(task) || _state.value.isSubmitting || _state.value.originalAttempt != null) return
        drafts.remove(task)
        _state.update { it.copy(activeForm = null, retainedForm = null, targetProposalPublicId = null, amountInput = "", noteInput = "",
            formCurrencyCode = null, formRowVersion = null, formProposedAmount = null, paymentTime = null, validationError = null) }
    }

    fun submit(task: DebtTask, expectedRowVersion: Long, currency: CurrencyCode?) {
        if (!matches(task) || _state.value.isSubmitting) return
        if (_state.value.originalAttempt != null) { retryOriginal(task); return }
        val current = _state.value
        val form = current.activeForm ?: return
        if (currency == null) {
            _state.update { it.copy(validationError = UiText.res(R.string.debt_action_currency_unsupported)) }
            return
        }
        if (current.formCurrencyCode != null && current.formCurrencyCode != currency.storageKey) {
            _state.update { it.copy(validationError = UiText.res(R.string.debt_proposal_currency_mismatch)) }
            return
        }
        val amount = parseAmountCents(current.amountInput, currency)
        val time = current.paymentTime?.resolve()
        proposalValidationError(form, amount, current.formProposedAmount, time)?.let { error ->
            _state.update { it.copy(validationError = UiText.res(error)) }
            return
        }
        val command = when (form) {
            ProposalForm.Propose -> MemberSettlementCommand.Propose(requireNotNull(amount), current.noteInput.trim().ifBlank { null },
                timeInput = time?.input)
            ProposalForm.Confirm -> MemberSettlementCommand.Confirm(current.targetProposalPublicId.orEmpty(), current.formRowVersion ?: expectedRowVersion,
                amount.takeIf { it != current.formProposedAmount })
        }
        _state.update { it.copy(formCurrencyCode = currency.storageKey, formRowVersion = current.formRowVersion ?: expectedRowVersion) }
        execute(task, command)
    }

    fun retryOriginal(task: DebtTask) {
        val original = _state.value.originalAttempt ?: return
        if (!original.rejected) execute(task, original.command)
    }

    /** Only a definite rejection permits an explicit new review against the current record. */
    fun reviewRejected(task: DebtTask, debt: Debt) {
        if (!matches(task) || !state.value.canModify || state.value.isSubmitting || state.value.originalAttempt?.rejected != true ||
            debt.publicId != task.debtPublicId) return
        _state.update { it.copy(originalAttempt = null, formRowVersion = debt.rowVersion, validationError = null, error = null,
            activeForm = it.retainedForm) }
        drafts.remove(task)
        drafts.write(_state.value)
    }

    fun withdraw(task: DebtTask, proposalPublicId: String) = execute(task, MemberSettlementCommand.Withdraw(proposalPublicId))
    fun reject(task: DebtTask, proposalPublicId: String) = execute(task, MemberSettlementCommand.Reject(proposalPublicId))
    fun forgive(task: DebtTask, expectedRowVersion: Long) = execute(task, MemberSettlementCommand.Forgive(expectedRowVersion))

    private fun execute(task: DebtTask, command: MemberSettlementCommand) {
        if (!matches(task) || _state.value.isSubmitting || repository.currentAccess()?.canModify != true) return
        val previous = _state.value.originalAttempt
        if (previous != null && (previous.command != command || previous.rejected)) return
        val original = previous ?: MemberSettlementAttempt(command, UUID.randomUUID().toString())
        _state.update { it.copy(originalAttempt = original) }
        drafts.write(_state.value)
        readJob?.cancel()
        _state.update { it.copy(isSubmitting = true, isLoading = false, error = null, validationError = null, flashMessage = null) }
        commandJob = viewModelScope.launch {
            if (!matches(task)) return@launch
            val result = repository.submit(task, command, original.key)
            currentCoroutineContext().ensureActive()
            if (!matches(task)) return@launch
            result.fold(
                onSuccess = { outcome ->
                    drafts.remove(task)
                    _state.update { it.withMemberResult(command, outcome) }
                    reload(task, acknowledged = true)
                },
                onFailure = { error ->
                    _state.update { it.withMemberFailure(command, error).copy(originalAttempt = original.copy(rejected = error.memberCommandRejected())) }
                    drafts.write(_state.value)
                },
            )
        }
    }

    fun dismissFlash() { _state.update { it.copy(flashMessage = null) } }
}

private fun Throwable.memberCommandRejected(): Boolean {
    val error = this as? RepositoryException ?: return false
    if (error.errorCode in setOf("idempotency_key_in_progress", "idempotency_key_reused")) return false
    return error.httpStatusCode in setOf(400, 405, 410, 412, 422) || error.httpStatusCode == 409 && error.errorCode in setOf(
        "state_conflict", "debt_already_voided", "repayment_proposal_already_pending", "repayment_proposal_expired",
        "repayment_proposal_not_pending", "debt_overpay_rejected",
    )
}

private fun initialPaymentTime(form: ProposalForm, proposal: MemberRepaymentProposal?, debt: Debt?, clock: Clock): ExpenseTimeForm {
    if (form == ProposalForm.Propose) return initialDebtPaymentTime(debt, clock)
    val calendar = debt?.repaymentCalendar
    val zone = calendar?.timezoneName?.let(ZoneId::of) ?: clock.zone
    return ExpenseTimeForm.initial(proposal?.paidAt, proposal?.accountingTime, null, zone)
}

private fun MemberProposalUiState.withMemberResult(
    command: MemberSettlementCommand,
    outcome: MemberSettlementResult,
): MemberProposalUiState {
    val nextProposals = when (outcome) {
        is MemberSettlementResult.Proposal -> listOf(outcome.value) + proposals.filterNot { it.publicId == outcome.value.publicId }
        is MemberSettlementResult.DebtChanged -> if (command is MemberSettlementCommand.Confirm) {
            proposals.filterNot { it.publicId == command.proposalPublicId }
        } else proposals
    }
    return copy(acknowledgedCommandRevision = acknowledgedCommandRevision + 1,
        isSubmitting = false, activeForm = null, retainedForm = null, originalAttempt = null, targetProposalPublicId = null,
        amountInput = "", noteInput = "", paymentTime = null, formCurrencyCode = null, formRowVersion = null, formProposedAmount = null,
        validationError = null, error = null, proposals = nextProposals,
        committedDebt = (outcome as? MemberSettlementResult.DebtChanged)?.value ?: committedDebt,
        flashMessage = UiText.res(memberCommandDoneRes(command)))
}

private fun MemberProposalUiState.withMemberFailure(command: MemberSettlementCommand, error: Throwable): MemberProposalUiState {
    val rejected = error.memberCommandRejected()
    val message = if (!rejected) UiText.res(R.string.debt_proposal_original_unknown) else if (command is MemberSettlementCommand.Forgive) {
        if ((error as? RepositoryException)?.errorCode == "state_conflict") UiText.res(R.string.debt_member_forgive_conflict)
        else error.toUiText(R.string.debt_member_forgive_failed)
    } else error.toUiText(R.string.debt_proposal_action_failed)
    return if (activeForm != null) copy(isSubmitting = false, validationError = message)
        else copy(isSubmitting = false, error = message, errorTone = if (rejected) MessageTone.Danger else MessageTone.Info)
}

@StringRes
private fun memberCommandDoneRes(command: MemberSettlementCommand): Int = when (command) {
    is MemberSettlementCommand.Propose -> R.string.debt_proposal_propose_done
    is MemberSettlementCommand.Confirm -> R.string.debt_proposal_confirm_done
    is MemberSettlementCommand.Withdraw -> R.string.debt_proposal_withdraw_done
    is MemberSettlementCommand.Reject -> R.string.debt_proposal_reject_done
    is MemberSettlementCommand.Forgive -> R.string.debt_member_forgive_done
}

/** 表单输入的校验文案 res，输入可接受时返回 null。 */
@StringRes
private fun proposalValidationError(
    form: ProposalForm,
    amountCents: Long?,
    proposedAmountCents: Long?,
    time: com.ticketbox.viewmodel.ExpenseTimeResolution?,
): Int? = when {
    amountCents == null || amountCents <= 0L -> R.string.debt_proposal_amount_validation
    // 部分确认不得超过对方提出的金额（后端也会 422，这里给即时反馈）。
    form == ProposalForm.Confirm && proposedAmountCents != null && amountCents > proposedAmountCents ->
        R.string.debt_proposal_confirm_over
    form == ProposalForm.Propose && time?.input == null -> time?.error ?: R.string.calendar_input_rule_required
    else -> null
}
