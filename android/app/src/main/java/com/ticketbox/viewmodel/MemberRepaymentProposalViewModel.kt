package com.ticketbox.viewmodel

import androidx.annotation.StringRes
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.DebtProposalActions
import com.ticketbox.domain.model.MemberRepaymentProposal
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * ADR-0049 §3.2 (slice 8d) 成员欠款 repayment proposal 收发箱 —— 详情屏对**成员**欠款渲染的
 * proposal 收发箱所用 ViewModel（与处理 external/manual 直接写的 [DebtDetailViewModel] 互斥）。
 *
 * 角色由**服务端权威字段** [com.ticketbox.domain.model.Debt.viewerIsDebtor] 给出（客户端不推导——它不
 * 知自己的 account_id，且成员债的同账本 owner 与同账本成员 counterparty 后端都返回 ledgerId 非空，§5.2）：
 * **债务人**发起「我已还款」/ 撤回（§3.2），**债权人**确认（全额或部分）/ 拒绝。只有 confirm 改变折叠（带 §2.1 OCC 载体=宿主 [Debt] 的
 * `rowVersion`，由详情屏在 [submit] 时传入），成功后 [MemberProposalUiState.foldChangedAt] 自增让宿主详
 * 情屏刷新欠款摘要；propose/withdraw/reject 不动折叠。所有写直接在线提交（无 outbox）；viewer 角色由
 * repository 在网络前短路。
 */
data class MemberProposalUiState(
    val isLoading: Boolean = false,
    val canModify: Boolean = true,
    val proposals: List<MemberRepaymentProposal> = emptyList(),
    val error: UiText? = null,
    val activeForm: ProposalForm? = null,
    val targetProposalPublicId: String? = null,
    val amountInput: String = "",
    val noteInput: String = "",
    val validationError: UiText? = null,
    val isSubmitting: Boolean = false,
    val flashMessage: UiText? = null,
    // 每次 confirm 提交还款（改变折叠）后自增，让宿主详情屏据此刷新欠款摘要；
    // propose/withdraw/reject 不改折叠，故不动它。
    val foldChangedAt: Int = 0,
) {
    /** 唯一的待确认 proposal（§3.2 一债一待确认），没有则为 null。 */
    val pendingProposal: MemberRepaymentProposal? get() = proposals.firstOrNull { it.isPending }
}

/** 详情屏 proposal 收发箱里需要表单输入的两类动作（withdraw/reject 无输入，直接触发）。 */
enum class ProposalForm { Propose, Confirm }

class MemberRepaymentProposalViewModel(
    private val repository: DebtProposalActions,
) : ViewModel() {

    private val _state = MutableStateFlow(MemberProposalUiState(canModify = repository.canModifyLedger()))
    val state: StateFlow<MemberProposalUiState> = _state.asStateFlow()

    private var debtPublicId: String? = null

    fun load(publicId: String) {
        debtPublicId = publicId
        // 切换到另一笔成员欠款时先清空旧 proposal，避免在新欠款下短暂看到上一笔的收发箱（隔离）。
        _state.update { it.copy(proposals = emptyList(), error = null, activeForm = null, validationError = null) }
        refresh()
    }

    fun refresh() {
        val publicId = debtPublicId ?: return
        _state.update { it.copy(isLoading = true, error = null, canModify = repository.canModifyLedger()) }
        viewModelScope.launch {
            repository.listRepaymentProposals(publicId).fold(
                onSuccess = { proposals ->
                    _state.update { it.copy(isLoading = false, proposals = proposals, error = null) }
                },
                onFailure = { err ->
                    _state.update { it.copy(isLoading = false, error = err.toUiText(R.string.debt_proposal_load_failed)) }
                },
            )
        }
    }

    fun openForm(form: ProposalForm, proposal: MemberRepaymentProposal? = null) {
        _state.update {
            it.copy(
                activeForm = form,
                targetProposalPublicId = proposal?.publicId,
                // 确认表单预填 proposal 提出的金额（债权人可下调成部分确认）；发起表单留空。
                amountInput = proposal?.let { p -> centsToYuanInput(p.proposedAmountCents) }.orEmpty(),
                noteInput = "",
                validationError = null,
            )
        }
    }

    fun updateAmount(value: String) {
        _state.update { it.copy(amountInput = value, validationError = null) }
    }

    fun updateNote(value: String) {
        _state.update { it.copy(noteInput = value, validationError = null) }
    }

    fun dismissForm() {
        _state.update {
            it.copy(
                activeForm = null,
                targetProposalPublicId = null,
                amountInput = "",
                noteInput = "",
                validationError = null,
                isSubmitting = false,
            )
        }
    }

    /**
     * 提交当前激活的表单。[expectedRowVersion] 是宿主欠款当前的 `row_version`（fold-changing 的确认走 §2.1
     * OCC 载体）；发起 proposal 不改折叠，忽略该参数。
     */
    fun submit(expectedRowVersion: Long) {
        val publicId = debtPublicId ?: return
        val current = _state.value
        val form = current.activeForm ?: return
        val amountCents = parseProposalYuanCents(current.amountInput)
        proposalValidationError(form, amountCents, current.pendingProposal?.proposedAmountCents)?.let { res ->
            _state.update { it.copy(validationError = UiText.res(res)) }
            return
        }
        val amount = amountCents ?: return
        _state.update { it.copy(isSubmitting = true) }
        viewModelScope.launch {
            val result: Result<Any> = when (form) {
                ProposalForm.Propose ->
                    repository.proposeRepayment(publicId, amount, current.noteInput, supersedesProposalPublicId = null)
                ProposalForm.Confirm ->
                    repository.confirmRepaymentProposal(
                        debtPublicId = publicId,
                        proposalPublicId = current.targetProposalPublicId.orEmpty(),
                        expectedRowVersion = expectedRowVersion,
                        // 等于提出金额=全额确认（confirmedAmountCents=null），否则=部分确认。
                        confirmedAmountCents = amount.takeIf { it != current.pendingProposal?.proposedAmountCents },
                    )
            }
            result.fold(
                onSuccess = { onActionSucceeded(actionDoneRes(form), foldChanged = form == ProposalForm.Confirm) },
                onFailure = { err ->
                    _state.update { it.copy(isSubmitting = false, validationError = err.toUiText(R.string.debt_proposal_action_failed)) }
                },
            )
        }
    }

    fun withdraw(proposalPublicId: String) {
        val publicId = debtPublicId ?: return
        _state.update { it.copy(isSubmitting = true) }
        viewModelScope.launch {
            repository.withdrawRepaymentProposal(publicId, proposalPublicId).fold(
                onSuccess = { onActionSucceeded(R.string.debt_proposal_withdraw_done, foldChanged = false) },
                onFailure = { err ->
                    _state.update { it.copy(isSubmitting = false, error = err.toUiText(R.string.debt_proposal_action_failed)) }
                },
            )
        }
    }

    fun reject(proposalPublicId: String) {
        val publicId = debtPublicId ?: return
        _state.update { it.copy(isSubmitting = true) }
        viewModelScope.launch {
            repository.rejectRepaymentProposal(publicId, proposalPublicId).fold(
                onSuccess = { onActionSucceeded(R.string.debt_proposal_reject_done, foldChanged = false) },
                onFailure = { err ->
                    _state.update { it.copy(isSubmitting = false, error = err.toUiText(R.string.debt_proposal_action_failed)) }
                },
            )
        }
    }

    fun dismissFlash() {
        _state.update { it.copy(flashMessage = null) }
    }

    /** 写成功的统一收尾：清表单 + 提示 + （仅 confirm）标记折叠已变 + 重拉 proposal 列表。 */
    private fun onActionSucceeded(@StringRes doneRes: Int, foldChanged: Boolean) {
        _state.update {
            it.copy(
                isSubmitting = false,
                activeForm = null,
                targetProposalPublicId = null,
                amountInput = "",
                noteInput = "",
                validationError = null,
                error = null,
                flashMessage = UiText.res(doneRes),
                foldChangedAt = if (foldChanged) it.foldChangedAt + 1 else it.foldChangedAt,
            )
        }
        refresh()
    }
}

/** 把元为单位的输入解析成本位币分（提出/确认金额都是正数），无法解析或为空返回 null。 */
private fun parseProposalYuanCents(input: String): Long? {
    val raw = input.trim()
    if (raw.isEmpty()) return null
    val yuan = raw.toDoubleOrNull() ?: return null
    return Math.round(yuan * 100)
}

/** 把本位币分格式化成元为单位的输入串（用于确认表单预填提出金额），不走浮点避免大额丢精度。 */
private fun centsToYuanInput(cents: Long): String = "${cents / 100}.${(cents % 100).toString().padStart(2, '0')}"

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

@StringRes
private fun actionDoneRes(form: ProposalForm): Int = when (form) {
    ProposalForm.Propose -> R.string.debt_proposal_propose_done
    ProposalForm.Confirm -> R.string.debt_proposal_confirm_done
}
