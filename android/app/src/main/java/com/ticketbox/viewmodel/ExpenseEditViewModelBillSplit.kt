package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.domain.model.BillSplitSent
import com.ticketbox.domain.model.BillSplitStatusValues
import com.ticketbox.domain.model.canInitiateBillSplit
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.parseAmountCents
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * UI/UX 第三波 批 13 — ExpenseEditViewModel 的拆账发起（bill-split invite）扩展。
 *
 * ADR-0029 跨账本拆账：从一笔**已确认**账单向**本账本成员**发起拆账邀请（产品拍板③
 * 收窄收件人为本账本成员；后端实际允许任意账号）。对方在自己的账本记一笔，接受后与
 * 本账单解耦。**在线-only**：直连失败直接报错，不入 outbox 离线队列（该面无幂等键）。
 *
 * 与主 ViewModel 同包，用 `internal` 字段访问（items/splits 编辑器先例模式）。
 * 卡片可见性判断 [canInitiateBillSplit] 在 domain（UI 与 VM 共用，避免漂移）。
 */

/** 本票已活跃（invited/accepted）的拆账总额——发起金额上限 = 父金额 − 该总额。 */
internal fun List<BillSplitSent>.activeSplitCentsFor(expenseId: Long): Long =
    filter { it.senderExpenseId == expenseId && it.isActiveSplit }
        .sumOf { it.amountCents }

private val BillSplitSent.isActiveSplit: Boolean
    get() = status == BillSplitStatusValues.INVITED || status == BillSplitStatusValues.ACCEPTED

/**
 * 拉取本票已发出的拆账邀请。fetchBillSplitSent 返回**账号维度**的全部已发邀请，这里按
 * senderExpenseId 客户端过滤出本票的（隐私上 sent 视图本就只含发起方自己的邀请）。
 * 仅在卡片可见（confirmed 等条件成立）时调用，避免对 pending/received 票做无谓请求。
 */
fun ExpenseEditViewModel.loadBillSplitSent() {
    val expense = _uiState.value.expense ?: return
    viewModelScope.launch {
        _uiState.update { it.copy(billSplitLoading = true, billSplitMessage = null) }
        repository.fetchBillSplitSent()
            .onSuccess { sent ->
                _uiState.update {
                    it.copy(
                        billSplitSent = sent.filter { row -> row.senderExpenseId == expense.id },
                        billSplitLoading = false,
                    )
                }
            }
            .onFailure { error ->
                _uiState.update {
                    it.copy(
                        billSplitLoading = false,
                        billSplitMessage = error.toUiText(R.string.expense_edit_bill_split_load_failed),
                    )
                }
            }
    }
}

/** 打开发起 sheet 并加载本账本成员（收件人候选）。仅在可发起时生效。 */
fun ExpenseEditViewModel.openBillSplitInviteSheet() {
    val expense = _uiState.value.expense ?: return
    if (!expense.canInitiateBillSplit(_uiState.value.readOnly)) return
    _uiState.update {
        it.copy(
            billSplitInviteSheetOpen = true,
            billSplitInviteSelectedMemberId = null,
            billSplitInviteAmountText = "",
            billSplitInviteMessage = null,
        )
    }
    loadBillSplitInviteMembers()
}

/** 加载本账本成员作为收件人候选：剔除自己（不能拆给自己）和已停用成员，只留可选的。 */
fun ExpenseEditViewModel.loadBillSplitInviteMembers() {
    viewModelScope.launch {
        _uiState.update { it.copy(billSplitInviteMembersLoading = true, billSplitInviteMessage = null) }
        repository.fetchSplitMembers()
            .onSuccess { members ->
                _uiState.update {
                    it.copy(
                        billSplitInviteMembers = members.filter { m -> !m.isSelf && !m.isDisabled },
                        billSplitInviteMembersLoading = false,
                    )
                }
            }
            .onFailure { error ->
                _uiState.update {
                    it.copy(
                        billSplitInviteMembersLoading = false,
                        billSplitInviteMessage = error.toUiText(R.string.expense_edit_bill_split_members_load_failed),
                    )
                }
            }
    }
}

fun ExpenseEditViewModel.selectBillSplitInviteMember(memberId: Long) {
    _uiState.update { it.copy(billSplitInviteSelectedMemberId = memberId, billSplitInviteMessage = null) }
}

fun ExpenseEditViewModel.updateBillSplitInviteAmount(amountText: String) {
    _uiState.update { it.copy(billSplitInviteAmountText = amountText, billSplitInviteMessage = null) }
}

fun ExpenseEditViewModel.closeBillSplitInviteSheet() {
    _uiState.update {
        it.copy(
            billSplitInviteSheetOpen = false,
            billSplitInviteSelectedMemberId = null,
            billSplitInviteAmountText = "",
            billSplitInviteMembers = emptyList(),
            billSplitInviteMessage = null,
        )
    }
}

/**
 * 发起拆账邀请。校验顺序：选了人 → 金额可解析 → 0 < 金额 ≤ 父金额 − 已活跃拆账额。
 * 客户端校验只为体验；后端 split_total_exceeds_parent / split_amount_* 仍是兜底权威。
 * **在线-only**：直连失败的 [Result.failure] 直接展示在 sheet 内，不入离线队列。
 */
fun ExpenseEditViewModel.sendBillSplitInvite() {
    val expense = _uiState.value.expense
    if (expense == null || expense.amountCents == null) {
        _uiState.update { it.copy(billSplitInviteMessage = UiText.res(R.string.expense_edit_page_not_loaded)) }
        return
    }
    val memberId = _uiState.value.billSplitInviteSelectedMemberId
    val member = _uiState.value.billSplitInviteMembers.firstOrNull { it.memberId == memberId }
    if (member == null) {
        _uiState.update { it.copy(billSplitInviteMessage = UiText.res(R.string.expense_edit_bill_split_pick_member)) }
        return
    }
    val amountCents = parseAmountCents(_uiState.value.billSplitInviteAmountText)
    if (amountCents == null || amountCents <= 0L) {
        _uiState.update { it.copy(billSplitInviteMessage = UiText.res(R.string.expense_edit_bill_split_amount_invalid)) }
        return
    }
    val remaining = expense.amountCents - _uiState.value.billSplitSent.activeSplitCentsFor(expense.id)
    if (amountCents > remaining) {
        _uiState.update { it.copy(billSplitInviteMessage = UiText.res(R.string.expense_edit_bill_split_amount_exceeds)) }
        return
    }
    viewModelScope.launch {
        _uiState.update { it.copy(billSplitInviteSending = true, billSplitInviteMessage = null) }
        repository.createBillSplitInvitation(expense.id, member.accountId, amountCents)
            .onSuccess {
                // 关闭 sheet、刷新本票已发列表（让新邀请立刻出现在卡里）、顶部成功提示。
                _uiState.update {
                    it.copy(
                        billSplitInviteSheetOpen = false,
                        billSplitInviteSelectedMemberId = null,
                        billSplitInviteAmountText = "",
                        billSplitInviteMembers = emptyList(),
                        billSplitInviteSending = false,
                        message = UiText.res(R.string.expense_edit_bill_split_sent),
                    )
                }
                loadBillSplitSent()
            }
            .onFailure { error ->
                // 在线-only：失败留在 sheet 内展示，不入队、不假装已发。
                _uiState.update {
                    it.copy(
                        billSplitInviteSending = false,
                        billSplitInviteMessage = error.toUiText(R.string.expense_edit_bill_split_send_failed),
                    )
                }
            }
    }
}

/** 撤回一条 invited 状态的拆账邀请（复用 cancel 动作）。成功后刷新本票已发列表。 */
fun ExpenseEditViewModel.cancelBillSplitInvitation(publicId: String) {
    viewModelScope.launch {
        _uiState.update { it.copy(billSplitLoading = true, billSplitMessage = null) }
        repository.cancelBillSplitInvitation(publicId)
            .onSuccess { loadBillSplitSent() }
            .onFailure { error ->
                _uiState.update {
                    it.copy(
                        billSplitLoading = false,
                        billSplitMessage = error.toUiText(R.string.expense_edit_bill_split_cancel_failed),
                    )
                }
            }
    }
}
