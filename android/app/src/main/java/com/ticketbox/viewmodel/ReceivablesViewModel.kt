package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.ReceivablesActions
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtLinkStatuses
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * 欠我的(应收) —— 服务端 viewer-personal 应收的只读发现面。
 *
 * 同账本 owner/member 应收与跨账本 member 债权人 shell 已由服务端按当前账号合并、去重；客户端
 * 不根据 owner-relative direction 重建当前主体身份。结果可包含 external 与 member 行，纯只读。
 *
 * 镜像 [DebtListViewModel] 的 [loadGeneration] 单调代际守卫。因为结果包含当前账本的同账本行，
 * [reload] 会在每次进入时同步清掉上一个账本的可见数据后再拉取。
 */
data class ReceivablesUiState(
    val isLoading: Boolean = false,
    val receivables: List<Debt> = emptyList(),
    val error: UiText? = null,
)

class ReceivablesViewModel(
    private val repository: ReceivablesActions,
) : ViewModel() {

    private val _state = MutableStateFlow(ReceivablesUiState())
    val state: StateFlow<ReceivablesUiState> = _state.asStateFlow()

    // Monotonic load token (mirrors DebtListViewModel): a refresh applies its result only if it is
    // still the latest. The init load + the refresh on every overlay (re-)entry each bump it, so a
    // slow earlier fetch can't overwrite newer data — it just drops.
    private var loadGeneration = 0L

    init {
        refresh()
    }

    fun reload() {
        _state.value = ReceivablesUiState()
        refresh()
    }

    fun refresh() {
        val gen = ++loadGeneration
        _state.update { it.copy(isLoading = true, error = null) }
        viewModelScope.launch {
            val result = repository.listReceivables()
            // Drop a load superseded by a newer refresh (which set isLoading and owns clearing it).
            if (gen != loadGeneration) return@launch
            result.fold(
                onSuccess = { debts ->
                    _state.update {
                        it.copy(
                            isLoading = false,
                            receivables = sortReceivablesActiveFirst(debts),
                            error = null,
                        )
                    }
                },
                onFailure = { err ->
                    _state.update {
                        it.copy(isLoading = false, error = err.toUiText(R.string.receivables_load_failed))
                    }
                },
            )
        }
    }
}

/**
 * Active-first ordering: open receivables first, cleared/voided recede to the bottom. The server
 * returns ``status.asc`` (alphabetical → cleared before open), so the client re-sorts — mirroring
 * the debt list's ``groupDebtsForList`` on both Android and web. Kotlin [sortedBy] is stable, so the
 * server's created order is preserved within a status rank.
 */
internal fun sortReceivablesActiveFirst(debts: List<Debt>): List<Debt> =
    debts.sortedBy { receivableStatusRank(it.status) }

private fun receivableStatusRank(status: String): Int = when (status) {
    DebtLinkStatuses.OPEN -> 0
    DebtLinkStatuses.CLEARED -> 1
    else -> 2 // voided / 未知
}
