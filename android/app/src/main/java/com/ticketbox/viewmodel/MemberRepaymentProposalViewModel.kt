package com.ticketbox.viewmodel

import androidx.annotation.StringRes
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
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
import com.ticketbox.ui.components.formatMinorAmountInput
import com.ticketbox.ui.components.parseAmountCents
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
    val task: DebtTask? = null,
    val isLoading: Boolean = false,
    val canModify: Boolean = false,
    val proposals: List<MemberRepaymentProposal> = emptyList(),
    val error: UiText? = null,
    val errorTone: MessageTone = MessageTone.Danger,
    val activeForm: ProposalForm? = null,
    val targetProposalPublicId: String? = null,
    val amountInput: String = "",
    val noteInput: String = "",
    val validationError: UiText? = null,
    val isSubmitting: Boolean = false,
    val flashMessage: UiText? = null,
    val committedDebt: Debt? = null,
) {
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

enum class ProposalForm { Propose, Confirm }

/** Owns the current editing task and online attempt; the server owns proposals and committed folds. */
class MemberRepaymentProposalViewModel(private val repository: DebtProposalActions) : ViewModel() {
    private val _state = MutableStateFlow(MemberProposalUiState())
    val state: StateFlow<MemberProposalUiState> = _state.asStateFlow()
    private var readJob: Job? = null
    private var commandJob: Job? = null
    private var attempt: MemberSettlementAttempt? = null

    init {
        viewModelScope.launch {
            repository.observeAccess().collect {
                val access = repository.currentAccess()
                if (_state.value.task?.binding != null && _state.value.task?.binding != access?.binding) {
                    readJob?.cancel()
                    commandJob?.cancel()
                    attempt = null
                    _state.value = MemberProposalUiState()
                }
                _state.update { state -> state.copy(canModify = access?.canModify == true) }
            }
        }
    }

    private fun matches(task: DebtTask): Boolean =
        _state.value.task == task && repository.currentAccess()?.binding == task.binding

    fun load(task: DebtTask) {
        val access = repository.currentAccess() ?: return
        if (access.binding != task.binding) return
        if (_state.value.task == task) { refresh(); return }
        readJob?.cancel()
        commandJob?.cancel()
        attempt = null
        _state.value = MemberProposalUiState(task = task, canModify = access.canModify)
        refresh()
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

    fun openForm(task: DebtTask, form: ProposalForm, proposal: MemberRepaymentProposal? = null) {
        if (!matches(task) || _state.value.isSubmitting || repository.currentAccess()?.canModify != true) return
        _state.update { it.copy(activeForm = form, targetProposalPublicId = proposal?.publicId,
            amountInput = proposal?.let { row -> CurrencyCode.fromStorageKeyOrNull(row.homeCurrencyCode)
                ?.let { currency -> formatMinorAmountInput(row.proposedAmountCents, currency) } }.orEmpty(),
            noteInput = "", validationError = null) }
    }

    fun updateAmount(task: DebtTask, value: String) {
        if (matches(task) && !_state.value.isSubmitting) _state.update { it.copy(amountInput = value, validationError = null) }
    }

    fun updateNote(task: DebtTask, value: String) {
        if (matches(task) && !_state.value.isSubmitting) _state.update { it.copy(noteInput = value, validationError = null) }
    }

    fun dismissForm(task: DebtTask) {
        if (matches(task) && !_state.value.isSubmitting) _state.update {
            it.copy(activeForm = null, targetProposalPublicId = null, amountInput = "", noteInput = "", validationError = null)
        }
    }

    fun submit(task: DebtTask, expectedRowVersion: Long, currency: CurrencyCode?) {
        if (!matches(task) || _state.value.isSubmitting) return
        val current = _state.value
        val form = current.activeForm ?: return
        if (currency == null) {
            _state.update { it.copy(validationError = UiText.res(R.string.debt_action_currency_unsupported)) }
            return
        }
        val amount = when (form) {
            ProposalForm.Propose -> parseAmountCents(current.amountInput, currency)
            ProposalForm.Confirm -> {
                val pending = current.pendingProposal ?: return
                val proposalCurrency = CurrencyCode.fromStorageKeyOrNull(pending.homeCurrencyCode)
                if (proposalCurrency == null || proposalCurrency != currency) {
                    _state.update { it.copy(validationError = UiText.res(R.string.debt_proposal_currency_mismatch)) }
                    return
                }
                parseAmountCents(current.amountInput, proposalCurrency)
            }
        }
        proposalValidationError(form, amount, current.pendingProposal?.proposedAmountCents)?.let { error ->
            _state.update { it.copy(validationError = UiText.res(error)) }
            return
        }
        val command = when (form) {
            ProposalForm.Propose -> MemberSettlementCommand.Propose(requireNotNull(amount), current.noteInput.trim().ifBlank { null })
            ProposalForm.Confirm -> MemberSettlementCommand.Confirm(current.targetProposalPublicId.orEmpty(), expectedRowVersion,
                amount.takeIf { it != current.pendingProposal?.proposedAmountCents })
        }
        execute(task, command)
    }

    fun withdraw(task: DebtTask, proposalPublicId: String) = execute(task, MemberSettlementCommand.Withdraw(proposalPublicId))
    fun reject(task: DebtTask, proposalPublicId: String) = execute(task, MemberSettlementCommand.Reject(proposalPublicId))
    fun forgive(task: DebtTask, expectedRowVersion: Long) = execute(task, MemberSettlementCommand.Forgive(expectedRowVersion))

    private fun execute(task: DebtTask, command: MemberSettlementCommand) {
        if (!matches(task) || _state.value.isSubmitting || repository.currentAccess()?.canModify != true) return
        val original = attempt?.takeIf { it.command == command }
            ?: MemberSettlementAttempt(command, UUID.randomUUID().toString()).also { attempt = it }
        readJob?.cancel()
        _state.update { it.copy(isSubmitting = true, isLoading = false, error = null, validationError = null, flashMessage = null) }
        commandJob = viewModelScope.launch {
            if (!matches(task)) return@launch
            val result = repository.submit(task, command, original.key)
            currentCoroutineContext().ensureActive()
            if (!matches(task)) return@launch
            result.fold(
                onSuccess = { outcome ->
                    attempt = null
                    _state.update { it.withMemberResult(command, outcome) }
                    reload(task, acknowledged = true)
                },
                onFailure = { error -> _state.update { it.withMemberFailure(command, error) } },
            )
        }
    }

    fun dismissFlash() { _state.update { it.copy(flashMessage = null) } }
}

private data class MemberSettlementAttempt(val command: MemberSettlementCommand, val key: String)

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
    return copy(isSubmitting = false, activeForm = null, targetProposalPublicId = null, amountInput = "", noteInput = "",
        validationError = null, error = null, proposals = nextProposals,
        committedDebt = (outcome as? MemberSettlementResult.DebtChanged)?.value ?: committedDebt,
        flashMessage = UiText.res(memberCommandDoneRes(command)))
}

private fun MemberProposalUiState.withMemberFailure(command: MemberSettlementCommand, error: Throwable): MemberProposalUiState {
    val message = if (command is MemberSettlementCommand.Forgive) {
        if ((error as? RepositoryException)?.errorCode == "state_conflict") UiText.res(R.string.debt_member_forgive_conflict)
        else error.toUiText(R.string.debt_member_forgive_failed)
    } else error.toUiText(R.string.debt_proposal_action_failed)
    return if (activeForm != null) copy(isSubmitting = false, validationError = message)
        else copy(isSubmitting = false, error = message, errorTone = MessageTone.Danger)
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
): Int? = when {
    amountCents == null || amountCents <= 0L -> R.string.debt_proposal_amount_validation
    // 部分确认不得超过对方提出的金额（后端也会 422，这里给即时反馈）。
    form == ProposalForm.Confirm && proposedAmountCents != null && amountCents > proposedAmountCents ->
        R.string.debt_proposal_confirm_over
    else -> null
}
