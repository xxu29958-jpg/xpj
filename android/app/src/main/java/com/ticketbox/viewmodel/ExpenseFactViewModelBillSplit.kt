package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.domain.model.BillSplitSent
import com.ticketbox.domain.model.BillSplitStatusValues
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.domain.model.canInitiateBillSplit
import com.ticketbox.ui.components.parseAmountCents
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * A1: 拆账邀请域 —— 从旧编辑 VM（ExpenseEditViewModelBillSplit.kt）迁移到
 * 事实页 Owner，能力不丢：已发列表 / 发起 sheet / 撤回。
 * 语义不变：ADR-0029 跨账本拆账，**在线-only**（直连失败直接报错，不入 outbox）。
 */

/** 本票已活跃（invited/accepted）的拆账总额——发起金额上限 = 父金额 − 该总额。 */
internal fun List<BillSplitSent>.factActiveSplitCentsFor(expenseId: Long): Long =
    filter { it.senderExpenseId == expenseId && it.isActiveSplit }
        .sumOf { it.amountCents }

private val BillSplitSent.isActiveSplit: Boolean
    get() = status == BillSplitStatusValues.INVITED || status == BillSplitStatusValues.ACCEPTED

private data class FactBillSplitInviteRequest(
    val expenseId: Long,
    val receiverAccountId: Long,
    val amountCents: Long,
)

/** 拉取本票已发出的拆账邀请（账号维度返回后按 senderExpenseId 客户端过滤）。 */
fun ExpenseFactViewModel.loadBillSplitSent() {
    val expense = _uiState.value.expense ?: return
    viewModelScope.launch {
        _uiState.update {
            it.copy(
                billSplitLoading = true,
                billSplitSentLoadState = BillSplitSentLoadState.Loading,
                billSplitMessage = null,
                billSplitMessageTone = MessageTone.Neutral,
            )
        }
        repository.fetchBillSplitSent()
            .onSuccess { sent ->
                _uiState.update {
                    it.copy(
                        billSplitSent = sent.filter { row -> row.senderExpenseId == expense.id },
                        billSplitSentLoadState = BillSplitSentLoadState.Loaded,
                        billSplitLoading = false,
                        billSplitMessageTone = MessageTone.Neutral,
                    )
                }
            }
            .onFailure { error ->
                _uiState.update {
                    it.copy(
                        billSplitSentLoadState = BillSplitSentLoadState.Failed,
                        billSplitLoading = false,
                        billSplitMessage = error.toUiText(R.string.expense_edit_bill_split_load_failed),
                        billSplitMessageTone = MessageTone.Danger,
                    )
                }
            }
    }
}

/** 打开发起 sheet 并加载本账本成员（收件人候选）。仅在可发起时生效。 */
fun ExpenseFactViewModel.openBillSplitInviteSheet() {
    val expense = _uiState.value.expense ?: return
    if (!expense.canInitiateBillSplit(_uiState.value.readOnly)) return
    _uiState.update {
        it.copy(
            billSplitInviteSheetOpen = true,
            billSplitInviteSelectedMemberId = null,
            billSplitInviteAmountText = "",
            billSplitInviteMessage = null,
            billSplitInviteMessageTone = MessageTone.Neutral,
        )
    }
    loadBillSplitInviteMembers()
}

private fun ExpenseFactViewModel.loadBillSplitInviteMembers() {
    viewModelScope.launch {
        _uiState.update {
            it.copy(
                billSplitInviteMembersLoading = true,
                billSplitInviteMessage = null,
                billSplitInviteMessageTone = MessageTone.Neutral,
            )
        }
        repository.fetchSplitMembers()
            .onSuccess { members ->
                _uiState.update {
                    it.copy(
                        billSplitInviteMembers = members.filter { m -> !m.isSelf && !m.isDisabled },
                        billSplitInviteMembersLoading = false,
                        billSplitInviteMessageTone = MessageTone.Neutral,
                    )
                }
            }
            .onFailure { error ->
                _uiState.update {
                    it.copy(
                        billSplitInviteMembersLoading = false,
                        billSplitInviteMessage = error.toUiText(R.string.expense_edit_bill_split_members_load_failed),
                        billSplitInviteMessageTone = MessageTone.Danger,
                    )
                }
            }
    }
}

fun ExpenseFactViewModel.selectBillSplitInviteMember(memberId: Long) {
    _uiState.update {
        it.copy(
            billSplitInviteSelectedMemberId = memberId,
            billSplitInviteMessage = null,
            billSplitInviteMessageTone = MessageTone.Neutral,
        )
    }
}

fun ExpenseFactViewModel.updateBillSplitInviteAmount(amountText: String) {
    _uiState.update {
        it.copy(
            billSplitInviteAmountText = amountText,
            billSplitInviteMessage = null,
            billSplitInviteMessageTone = MessageTone.Neutral,
        )
    }
}

fun ExpenseFactViewModel.closeBillSplitInviteSheet() {
    _uiState.update {
        it.copy(
            billSplitInviteSheetOpen = false,
            billSplitInviteSelectedMemberId = null,
            billSplitInviteAmountText = "",
            billSplitInviteMembers = emptyList(),
            billSplitInviteMessage = null,
            billSplitInviteMessageTone = MessageTone.Neutral,
        )
    }
}

/** 发起拆账邀请：选了人 → 金额可解析 → 0 < 金额 ≤ 父金额 − 已活跃拆账额。 */
fun ExpenseFactViewModel.sendBillSplitInvite() {
    val request = currentBillSplitInviteRequest() ?: return
    viewModelScope.launch {
        _uiState.update {
            it.copy(
                billSplitInviteSending = true,
                billSplitInviteMessage = null,
                billSplitInviteMessageTone = MessageTone.Neutral,
            )
        }
        repository.createBillSplitInvitation(request.expenseId, request.receiverAccountId, request.amountCents)
            .onSuccess { sent ->
                _uiState.update {
                    it.copy(
                        billSplitSent = it.billSplitSent.upsertBillSplitSent(sent, request.expenseId),
                        billSplitSentLoadState = BillSplitSentLoadState.Loading,
                        billSplitLoading = true,
                        billSplitInviteSheetOpen = false,
                        billSplitInviteSelectedMemberId = null,
                        billSplitInviteAmountText = "",
                        billSplitInviteMembers = emptyList(),
                        billSplitInviteSending = false,
                        message = UiText.res(R.string.expense_edit_bill_split_sent),
                        messageTone = MessageTone.Success,
                    )
                }
                loadBillSplitSent()
            }
            .onFailure { error ->
                _uiState.update {
                    it.copy(
                        billSplitInviteSending = false,
                        billSplitInviteMessage = error.toUiText(R.string.expense_edit_bill_split_send_failed),
                        billSplitInviteMessageTone = MessageTone.Danger,
                    )
                }
            }
    }
}

private fun ExpenseFactViewModel.currentBillSplitInviteRequest(): FactBillSplitInviteRequest? {
    fun reject(message: UiText): FactBillSplitInviteRequest? {
        _uiState.update {
            it.copy(
                billSplitInviteMessage = message,
                billSplitInviteMessageTone = MessageTone.Danger,
            )
        }
        return null
    }

    val expense = _uiState.value.expense
    if (expense == null || expense.amountCents == null) {
        return reject(UiText.res(R.string.expense_edit_page_not_loaded))
    }
    val memberId = _uiState.value.billSplitInviteSelectedMemberId
    val member = _uiState.value.billSplitInviteMembers.firstOrNull { it.memberId == memberId }
    if (member == null) {
        return reject(UiText.res(R.string.expense_edit_bill_split_pick_member))
    }
    val currency = expense.editParseCurrency()
        ?: return reject(UiText.res(R.string.expense_edit_currency_unsupported))
    val amountCents = parseAmountCents(_uiState.value.billSplitInviteAmountText, currency)
    if (amountCents == null || amountCents <= 0L) {
        return reject(UiText.res(R.string.expense_edit_bill_split_amount_invalid))
    }
    if (_uiState.value.billSplitSentLoadState == BillSplitSentLoadState.Loaded) {
        val remaining = expense.amountCents - _uiState.value.billSplitSent.factActiveSplitCentsFor(expense.id)
        if (amountCents > remaining) {
            return reject(UiText.res(R.string.expense_edit_bill_split_amount_exceeds))
        }
    }
    return FactBillSplitInviteRequest(expenseId = expense.id, receiverAccountId = member.accountId, amountCents = amountCents)
}

/** 撤回一条 invited 状态的拆账邀请。成功后刷新本票已发列表。 */
fun ExpenseFactViewModel.cancelBillSplitInvitation(publicId: String) {
    viewModelScope.launch {
        _uiState.update {
            it.copy(
                billSplitLoading = true,
                billSplitMessage = null,
                billSplitMessageTone = MessageTone.Neutral,
            )
        }
        repository.cancelBillSplitInvitation(publicId)
            .onSuccess { cancelled ->
                _uiState.update { state ->
                    val expenseId = state.expense?.id
                    state.copy(
                        billSplitSent = state.billSplitSent.upsertBillSplitSent(cancelled, expenseId),
                        billSplitSentLoadState = BillSplitSentLoadState.Loading,
                        billSplitLoading = true,
                        billSplitMessage = null,
                        billSplitMessageTone = MessageTone.Neutral,
                    )
                }
                loadBillSplitSent()
            }
            .onFailure { error ->
                _uiState.update {
                    it.copy(
                        billSplitLoading = false,
                        billSplitMessage = error.toUiText(R.string.expense_edit_bill_split_cancel_failed),
                        billSplitMessageTone = MessageTone.Danger,
                    )
                }
            }
    }
}

private fun List<BillSplitSent>.upsertBillSplitSent(
    updated: BillSplitSent,
    expenseId: Long?,
): List<BillSplitSent> {
    if (expenseId == null || updated.senderExpenseId != expenseId) return this
    val existingIndex = indexOfFirst { it.publicId == updated.publicId }
    if (existingIndex == -1) return this + updated
    return map { row -> if (row.publicId == updated.publicId) updated else row }
}
