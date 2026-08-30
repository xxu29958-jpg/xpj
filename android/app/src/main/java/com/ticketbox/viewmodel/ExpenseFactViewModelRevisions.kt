package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.domain.model.MessageTone
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

private const val REVISION_PAGE_SIZE = 50

/**
 * A1: 变更记录时间线 —— 真实读取 GET revisions（在线-only；离线展示既有缓存
 * 内容或诚实错误态，不伪造 revision）；分页 append 只追加、去重，不改写已加载页。
 * 展示模型/mapper 在 ExpenseFactTimelineModels.kt。
 */

fun ExpenseFactViewModel.loadExpenseRevisions() {
    viewModelScope.launch {
        _uiState.update {
            it.copy(
                revisionsLoading = true,
                revisionsLoadState = ExpenseDetailDataLoadState.Loading,
                revisionsOlderLoading = false,
                revisionsOlderLoadFailed = false,
            )
        }
        repository.fetchExpenseRevisions(expenseId, page = 1, pageSize = REVISION_PAGE_SIZE)
            .onSuccess { page ->
                _uiState.update {
                    it.copy(
                        revisions = page.items,
                        revisionsTotal = page.total,
                        revisionsLoading = false,
                        revisionsLoadState = ExpenseDetailDataLoadState.Loaded,
                        revisionsNextPage = page.nextPageOrNull(),
                        revisionsOlderLoading = false,
                        revisionsOlderLoadFailed = false,
                    )
                }
            }
            .onFailure { error ->
                _uiState.update {
                    it.copy(
                        revisionsLoading = false,
                        revisionsLoadState = ExpenseDetailDataLoadState.Failed,
                        revisions = emptyList(),
                        revisionsTotal = 0,
                        revisionsNextPage = null,
                        revisionsOlderLoading = false,
                        revisionsOlderLoadFailed = false,
                        message = error.toUiText(R.string.expense_fact_revisions_failed),
                        messageTone = MessageTone.Danger,
                    )
                }
            }
    }
}

fun ExpenseFactViewModel.loadOlderExpenseRevisions() {
    val nextPage = _uiState.value.revisionsNextPage ?: return
    if (_uiState.value.revisionsOlderLoading) return
    viewModelScope.launch {
        _uiState.update {
            it.copy(
                revisionsOlderLoading = true,
                revisionsOlderLoadFailed = false,
            )
        }
        repository.fetchExpenseRevisions(expenseId, page = nextPage, pageSize = REVISION_PAGE_SIZE)
            .onSuccess { page ->
                _uiState.update { state ->
                    val known = state.revisions.asSequence().map { it.publicId }.toHashSet()
                    state.copy(
                        revisions = state.revisions + page.items.filter { known.add(it.publicId) },
                        revisionsTotal = page.total,
                        revisionsNextPage = page.nextPageOrNull(),
                        revisionsOlderLoading = false,
                        revisionsOlderLoadFailed = false,
                    )
                }
            }
            .onFailure {
                _uiState.update {
                    it.copy(
                        revisionsOlderLoading = false,
                        revisionsOlderLoadFailed = true,
                    )
                }
            }
    }
}

fun ExpenseFactViewModel.loadRevisionMemberNames() {
    viewModelScope.launch {
        repository.fetchSplitMembers()
            .onSuccess { members ->
                _uiState.update { state ->
                    state.copy(
                        revisionMemberNames = members.associate { it.memberId to it.displayName },
                    )
                }
            }
    }
}

private fun com.ticketbox.domain.model.ExpenseRevisionPage.nextPageOrNull(): Int? =
    if (page * pageSize < total) page + 1 else null

fun ExpenseFactViewModel.toggleTimelineExpanded() {
    _uiState.update { it.copy(timelineExpanded = !it.timelineExpanded) }
}
