package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

private const val REVISION_PAGE_SIZE = 50

/**
 * A1: 变更记录时间线 —— 真实读取 GET revisions（在线-only；离线展示既有缓存
 * 内容或诚实错误态，不伪造 revision）；分页 append 只追加、去重，不改写已加载页。
 * 展示模型/mapper 在 ExpenseFactTimelineModels.kt。
 */

fun ExpenseFactViewModel.loadExpenseRevisions() {
    val generation = ++revisionLoadGeneration
    viewModelScope.launch {
        if (generation != revisionLoadGeneration) return@launch
        _uiState.update { state ->
            state.copy(
                revisionsLoading = true,
                revisionsLoadState = if (state.revisions.isEmpty()) {
                    ExpenseDetailDataLoadState.Loading
                } else {
                    ExpenseDetailDataLoadState.Loaded
                },
                revisionsOlderLoading = false,
                revisionsOlderLoadFailed = false,
                revisionsRefreshFailed = false,
            )
        }
        repository.fetchExpenseRevisions(expenseId, page = 1, pageSize = REVISION_PAGE_SIZE)
            .onSuccess { page ->
                _uiState.update { state ->
                    if (generation != revisionLoadGeneration) return@update state
                    state.copy(
                        revisions = page.items,
                        revisionsTotal = page.total,
                        revisionsLoading = false,
                        revisionsLoadState = ExpenseDetailDataLoadState.Loaded,
                        revisionsNextPage = page.nextPageOrNull(),
                        revisionsOlderLoading = false,
                        revisionsOlderLoadFailed = false,
                        revisionsRefreshFailed = false,
                    )
                }
            }
            .onFailure {
                _uiState.update { state ->
                    if (generation != revisionLoadGeneration) return@update state
                    if (state.revisions.isNotEmpty()) {
                        state.copy(
                            revisionsLoading = false,
                            revisionsLoadState = ExpenseDetailDataLoadState.Loaded,
                            revisionsOlderLoading = false,
                            revisionsOlderLoadFailed = false,
                            revisionsRefreshFailed = true,
                        )
                    } else {
                        state.copy(
                            revisionsLoading = false,
                            revisionsLoadState = ExpenseDetailDataLoadState.Failed,
                            revisions = emptyList(),
                            revisionsTotal = 0,
                            revisionsNextPage = null,
                            revisionsOlderLoading = false,
                            revisionsOlderLoadFailed = false,
                            revisionsRefreshFailed = false,
                        )
                    }
                }
            }
    }
}

fun ExpenseFactViewModel.loadOlderExpenseRevisions() {
    val nextPage = _uiState.value.revisionsNextPage ?: return
    if (_uiState.value.revisionsOlderLoading) return
    val generation = revisionLoadGeneration
    viewModelScope.launch {
        if (generation != revisionLoadGeneration || _uiState.value.revisionsNextPage != nextPage) {
            return@launch
        }
        _uiState.update { state ->
            state.copy(
                revisionsOlderLoading = true,
                revisionsOlderLoadFailed = false,
            )
        }
        repository.fetchExpenseRevisions(expenseId, page = nextPage, pageSize = REVISION_PAGE_SIZE)
            .onSuccess { page ->
                _uiState.update { state ->
                    if (generation != revisionLoadGeneration || state.revisionsNextPage != nextPage) {
                        return@update state
                    }
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
                _uiState.update { state ->
                    if (generation != revisionLoadGeneration || state.revisionsNextPage != nextPage) {
                        return@update state
                    }
                    state.copy(
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
