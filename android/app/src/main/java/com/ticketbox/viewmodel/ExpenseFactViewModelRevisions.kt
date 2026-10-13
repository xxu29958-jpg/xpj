package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

private const val REVISION_PAGE_SIZE = 50

/**
 * 变更记录时间线 —— GET revisions 与带读取时间的持久快照；分页 append
 * 只追加、去重，不改写已加载页，也不把旧历史当当前事实的接受回执。
 * A1 P2: 首读/显式刷新不传锚，服务端冻结 snapshot_revision 并随 response 返回；
 * 之后 loadOlder 回传同一锚，所有页都属于同一不可变前缀（revision_number <= 锚），
 * 后台新增 revision 不会让记录重复/漏失/最早不可达。dedup 只防重复点击。
 * 展示模型/mapper 在 ExpenseFactTimelineModels.kt。
 */

fun ExpenseFactViewModel.loadExpenseRevisions() {
    val binding = _uiState.value.correctionAccess?.binding ?: return
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
        repository.fetchExpenseRevisions(expenseId, page = 1, pageSize = REVISION_PAGE_SIZE, snapshot = null,
            expectedBinding = binding)
            .onSuccess { snapshot ->
                val page = snapshot.value
                _uiState.update { state ->
                    if (generation != revisionLoadGeneration) return@update state
                    state.copy(
                        revisions = page.items,
                        revisionsTotal = page.total,
                        revisionsLoading = false,
                        revisionsLoadState = ExpenseDetailDataLoadState.Loaded,
                        revisionsNextPage = page.nextPageOrNull(),
                        revisionsSnapshot = com.ticketbox.domain.model.ExpenseHistorySnapshot(page.snapshotRevision, page.offsetSnapshotId),
                        revisionsOlderLoading = false,
                        revisionsOlderLoadFailed = false,
                        revisionsRefreshFailed = false,
                        revisionsCachedAt = snapshot.fetchedAt.takeIf { snapshot.fromCache },
                    )
                }
            }
            .onFailure { error ->
                publishRevisionFailure(generation, error)
            }
    }
}

fun ExpenseFactViewModel.loadOlderExpenseRevisions() {
    val current = _uiState.value
    val binding = current.correctionAccess?.binding ?: return
    val nextPage = current.revisionsNextPage ?: return
    if (current.revisionsLoading || current.revisionsOlderLoading) return
    // 锚与 nextPage 同生同灭：只在首读/显式刷新成功后一起换新。
    val snapshot = current.revisionsSnapshot
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
            snapshot = snapshot,
            expectedBinding = binding,
        )
            .onSuccess { snapshotRead ->
                val page = snapshotRead.value
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
                        revisionsCachedAt = state.revisionsCachedAt ?: snapshotRead.fetchedAt.takeIf { snapshotRead.fromCache },
                    )
                }
            }
            .onFailure { error ->
                publishRevisionFailure(generation, error, nextPage)
            }
    }
}

/** Both history consumers retire denied reads and preserve only a still-authorized prefix. */
private fun ExpenseFactViewModel.publishRevisionFailure(generation: Long, error: Throwable, olderPage: Int? = null) {
    if (generation != revisionLoadGeneration || retireDeniedFactReads(error)) return
    _uiState.update { state ->
        when {
            olderPage != null && state.revisionsNextPage != olderPage -> state
            olderPage != null -> state.copy(revisionsOlderLoading = false, revisionsOlderLoadFailed = true)
            state.revisions.isNotEmpty() -> state.copy(revisionsLoading = false,
                revisionsLoadState = ExpenseDetailDataLoadState.Loaded, revisionsOlderLoading = false,
                revisionsOlderLoadFailed = false, revisionsRefreshFailed = true)
            else -> state.copy(revisionsLoading = false, revisionsLoadState = ExpenseDetailDataLoadState.Failed,
                revisions = emptyList(), revisionsTotal = 0, revisionsNextPage = null, revisionsSnapshot = null,
                revisionsCachedAt = null, revisionsOlderLoading = false, revisionsOlderLoadFailed = false, revisionsRefreshFailed = false)
        }
    }
}

fun ExpenseFactViewModel.loadRevisionMemberNames() {
    val binding = _uiState.value.correctionAccess?.binding ?: return
    viewModelScope.launch {
        if (binding != _uiState.value.correctionAccess?.binding) return@launch
        repository.fetchSplitMembers()
            .onSuccess { members ->
                _uiState.update { state ->
                    if (binding != state.correctionAccess?.binding) return@update state
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
