package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

private const val REVISION_PAGE_SIZE = 50

/**
 * A1: 变更记录时间线 —— 真实读取 GET revisions（在线-only；离线展示既有缓存
 * 内容或诚实错误态，不伪造 revision）；分页 append 只追加、去重，不改写已加载页。
 * A1 P2: 首读/显式刷新不传锚，服务端冻结 snapshot_revision 并随 response 返回；
 * 之后 loadOlder 回传同一锚，所有页都属于同一不可变前缀（revision_number <= 锚），
 * 后台新增 revision 不会让记录重复/漏失/最早不可达。dedup 只防重复点击。
 * 展示模型/mapper 在 ExpenseFactTimelineModels.kt。
 */

fun ExpenseFactViewModel.loadExpenseRevisions() {
    val generation = ++revisionLoadGeneration
    viewModelScope.launch {
        if (generation != revisionLoadGeneration) return@launch
        _uiState.update { state ->
            state.copy(
                revisionsLoading = true,
                revisionsLoadState = if (state.revisions.isEmpty()) ExpenseDetailDataLoadState.Loading else ExpenseDetailDataLoadState.Loaded,
                revisionsOlderLoading = false,
                revisionsOlderLoadFailed = false,
                revisionsRefreshFailed = false,
            )
        }
        repository.fetchExpenseRevisions(expenseId, page = 1, pageSize = REVISION_PAGE_SIZE, snapshotRevision = null)
            .onSuccess { page ->
                _uiState.update { state ->
                    if (generation != revisionLoadGeneration) return@update state
                    state.copy(
                        revisions = page.items,
                        revisionsTotal = page.total,
                        revisionsLoading = false,
                        revisionsLoadState = ExpenseDetailDataLoadState.Loaded,
                        revisionsNextPage = page.nextPageOrNull(),
                        revisionsSnapshotRevision = page.snapshotRevision,
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
                            revisionsSnapshotRevision = null,
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
    val current = _uiState.value
    val nextPage = current.revisionsNextPage ?: return
    if (current.revisionsLoading || current.revisionsOlderLoading) return
    // 锚与 nextPage 同生同灭：只在首读/显式刷新成功后一起换新。
    val snapshot = current.revisionsSnapshotRevision
    val generation = revisionLoadGeneration
    viewModelScope.launch {
        val state = _uiState.value
        if (
            generation != revisionLoadGeneration ||
            state.revisionsNextPage != nextPage ||
            state.revisionsLoading ||
            state.revisionsOlderLoading
        ) {
            return@launch
        }
        _uiState.update { state ->
            state.copy(
                revisionsOlderLoading = true,
                revisionsOlderLoadFailed = false,
            )
        }
        repository.fetchExpenseRevisions(
            expenseId,
            page = nextPage,
            pageSize = REVISION_PAGE_SIZE,
            snapshotRevision = snapshot,
        )
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
