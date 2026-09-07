package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.domain.model.BillSplitSent
import com.ticketbox.domain.model.BillSplitStatusValues
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.domain.model.canInitiateBillSplit
import com.ticketbox.ui.components.parseAmountCents
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

enum class BillSplitSentLoadState {
    Unknown,
    Loading,
    Loaded,
    Failed,
}

/**
 * A1: 拆账邀请域 —— 从已退役的确认后编辑责任迁移到事实页 Owner，
 * 能力不丢：已发列表 / 发起 sheet / 撤回。
 * 创建意图由 Room 接收，发送和重试只由已注册的 dispatcher 执行。
 */
internal fun List<BillSplitSent>.factActiveSplitCentsFor(expenseId: Long): Long =
    filter { it.senderExpenseId == expenseId && it.isActiveSplit }
        .sumOf { it.amountCents }

private val BillSplitSent.isActiveSplit: Boolean
    get() = status == BillSplitStatusValues.INVITED || status == BillSplitStatusValues.ACCEPTED

private data class FactBillSplitInviteRequest(
    val expense: com.ticketbox.domain.model.Expense,
    val receiverAccountId: Long,
    val receiverName: String,
    val amountCents: Long,
    val binding: LogicalSessionBinding,
)

/** 拉取本票已发出的拆账邀请（账号维度返回后按 senderExpenseId 客户端过滤）。 */
fun ExpenseFactViewModel.loadBillSplitSent(onlyIfUnknown: Boolean = false) {
    val expense = _uiState.value.expense ?: return
    val binding = _uiState.value.correctionAccess?.binding ?: return
    if (onlyIfUnknown && _uiState.value.billSplitSentLoadState != BillSplitSentLoadState.Unknown) return
    // Claim the first read before launch: root and bundle adoption can both reach this owner.
    _uiState.update {
        it.copy(
            billSplitLoading = true,
            billSplitSentLoadState = BillSplitSentLoadState.Loading,
            billSplitMessage = null,
            billSplitMessageTone = MessageTone.Neutral,
        )
    }
    viewModelScope.launch {
        if (binding != _uiState.value.correctionAccess?.binding) return@launch
        val result = repository.fetchBillSplitSent()
        if (binding != _uiState.value.correctionAccess?.binding) return@launch
        result
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
    if (hasPendingBillSplitCreation()) return
    if (blockUnreadyFactWrite()) return
    val expense = _uiState.value.expense ?: return
    val binding = _uiState.value.correctionAccess?.binding ?: return
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
    loadBillSplitInviteMembers(binding)
}

private fun ExpenseFactViewModel.loadBillSplitInviteMembers(binding: LogicalSessionBinding) {
    _uiState.update {
        it.copy(
            billSplitInviteMembersLoading = true,
            billSplitInviteMessage = null,
            billSplitInviteMessageTone = MessageTone.Neutral,
        )
    }
    viewModelScope.launch {
        if (binding != _uiState.value.correctionAccess?.binding) return@launch
        repository.fetchSplitMembers()
            .onSuccess { members ->
                if (binding != _uiState.value.correctionAccess?.binding) return@onSuccess
                _uiState.update {
                    it.copy(
                        billSplitInviteMembers = members.filter { m -> !m.isSelf && !m.isDisabled },
                        billSplitInviteMembersLoading = false,
                        billSplitInviteMessageTone = MessageTone.Neutral,
                    )
                }
            }
            .onFailure { error ->
                if (binding != _uiState.value.correctionAccess?.binding) return@onFailure
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
    if (_uiState.value.billSplitInviteSending) return
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
    if (_uiState.value.billSplitInviteSending) return
    val request = currentBillSplitInviteRequest() ?: return
    _uiState.update {
        it.copy(
            billSplitInviteSending = true,
            billSplitInviteMessage = null,
            billSplitInviteMessageTone = MessageTone.Neutral,
        )
    }
    viewModelScope.launch {
        if (request.binding != _uiState.value.correctionAccess?.binding) return@launch
        if (blockUnreadyFactWrite(request.expense.rowVersion)) {
            _uiState.update { it.copy(billSplitInviteSending = false) }
            return@launch
        }
        repository.createBillSplitInvitation(request.binding, request.expense, request.receiverAccountId, request.receiverName, request.amountCents)
            .onSuccess {
                if (request.binding != _uiState.value.correctionAccess?.binding) return@onSuccess
                _uiState.update {
                    it.copy(
                        billSplitInviteSheetOpen = false,
                        billSplitInviteSelectedMemberId = null,
                        billSplitInviteAmountText = "",
                        billSplitInviteMembers = emptyList(),
                        billSplitInviteSending = false,
                        message = UiText.res(R.string.bill_split_submission_saved),
                        messageTone = MessageTone.Neutral,
                    )
                }
            }
            .onFailure { error ->
                if (request.binding != _uiState.value.correctionAccess?.binding) return@onFailure
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
    if (blockUnreadyFactWrite() || hasPendingBillSplitCreation()) return null
    val binding = _uiState.value.correctionAccess?.binding ?: return null
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
    if (!expense.canInitiateBillSplit(_uiState.value.readOnly)) return null
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
    return FactBillSplitInviteRequest(expense, member.accountId, member.displayName, amountCents, binding)
}

/** 撤回一条 invited 状态的拆账邀请。成功后刷新本票已发列表。 */
fun ExpenseFactViewModel.cancelBillSplitInvitation(publicId: String) {
    val binding = _uiState.value.correctionAccess?.binding ?: return
    viewModelScope.launch {
        if (binding != _uiState.value.correctionAccess?.binding) return@launch
        _uiState.update {
            it.copy(
                billSplitLoading = true,
                billSplitMessage = null,
                billSplitMessageTone = MessageTone.Neutral,
            )
        }
        repository.cancelBillSplitInvitation(publicId)
            .onSuccess { cancelled ->
                if (binding != _uiState.value.correctionAccess?.binding) return@onSuccess
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
                if (binding != _uiState.value.correctionAccess?.binding) return@onFailure
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
