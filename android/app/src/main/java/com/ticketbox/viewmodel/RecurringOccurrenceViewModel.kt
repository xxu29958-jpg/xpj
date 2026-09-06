package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.remote.dto.RecurringOccurrenceDto
import com.ticketbox.data.remote.dto.RecurringOccurrencePaymentRequestDto
import com.ticketbox.data.repository.ConflictResolution
import com.ticketbox.data.repository.FailedResolution
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LedgerActions
import com.ticketbox.data.repository.OccurrencePaymentDraft
import com.ticketbox.data.repository.OutboxRepository
import com.ticketbox.data.repository.PendingOccurrencePayment
import com.ticketbox.data.repository.RecurringOccurrenceActions
import com.ticketbox.data.repository.occurrenceTarget
import com.ticketbox.domain.model.ConfirmedStreamItem
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.RecurringItem
import java.time.YearMonth
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class RecurringOccurrenceUiState(
    val access: LedgerAccessContext? = null,
    val item: RecurringItem? = null,
    val occurrence: RecurringOccurrenceDto? = null,
    val payments: List<ConfirmedStreamItem> = emptyList(),
    val queue: List<PendingOccurrencePayment> = emptyList(),
    val choice: OccurrencePaymentDraft? = null,
    val loading: Boolean = false,
    val saving: Boolean = false,
    val acceptedId: Long? = null,
    val requestedPeriod: String = "current",
    val message: String? = null,
) {
    val pending: List<PendingOccurrencePayment> get() = queue.filter {
        it.row.status != PendingMutationStatus.Done &&
            it.row.targetId == occurrenceTarget(item?.publicId.orEmpty(), occurrence?.period ?: requestedPeriod)
    }
    val canWrite: Boolean get() = access?.canModify == true && item?.status != "archived" &&
        occurrence?.state in setOf("unfulfilled", "fulfilled", "needs_review") && !loading && !saving &&
        pending.isEmpty() && (acceptedId == null || queue.any { it.row.id == acceptedId && it.row.status == PendingMutationStatus.Done })
}

class RecurringOccurrenceViewModel(
    private val repository: RecurringOccurrenceActions,
    private val ledger: LedgerActions,
    private val outbox: OutboxRepository,
    private val onChanged: () -> Unit = {},
) : ViewModel() {
    private val mutableState = MutableStateFlow(RecurringOccurrenceUiState(access = repository.currentAccess()))
    val uiState = mutableState.asStateFlow()
    private var epoch = 0L

    init {
        viewModelScope.launch {
            repository.observeAccess().collectLatest { access ->
                if (mutableState.value.access?.binding != access?.binding) {
                    epoch++
                    mutableState.value = RecurringOccurrenceUiState(access = access)
                } else mutableState.update { it.copy(access = access) }
                if (access != null) coroutineScope {
                    launch { ledger.observeConfirmedStream().collect { rows -> mutableState.update { it.copy(payments = rows) } } }
                    repository.observeQueue(access.binding).collect(::acceptQueue)
                }
            }
        }
    }

    fun open(item: RecurringItem) {
        if (item.ledgerId != mutableState.value.access?.binding?.ledgerId) return
        mutableState.update { it.copy(item = item, occurrence = null, choice = null, acceptedId = null, message = null, requestedPeriod = "current") }
        load("current")
    }

    fun dismiss() {
        if (mutableState.value.saving) return
        epoch++
        mutableState.update { it.copy(item = null, occurrence = null, choice = null, loading = false) }
    }

    fun changePeriod(period: String) {
        if (runCatching { YearMonth.parse(period).toString() == period }.getOrDefault(false)) {
            mutableState.update { it.copy(occurrence = null, choice = null, acceptedId = null, requestedPeriod = period) }
            load(period)
        } else mutableState.update { it.copy(message = "请输入年月，例如 2026-09。") }
    }

    fun refresh() = load(mutableState.value.occurrence?.period ?: mutableState.value.requestedPeriod)

    fun choose(payment: ConfirmedStreamItem.ExpenseRow?, currency: CurrencyCode) {
        val state = mutableState.value
        val occurrence = state.occurrence ?: return
        if (!state.canWrite) return
        val root = payment?.root
        mutableState.update { it.copy(choice = OccurrencePaymentDraft(
            occurrence = occurrence,
            seriesLabel = state.item?.merchant.orEmpty(),
            request = RecurringOccurrencePaymentRequestDto(
                action = if (payment == null) "clear" else "link",
                expectedRowVersion = occurrence.rowVersion,
                expectedSeriesRowVersion = occurrence.seriesRowVersion,
                expensePublicId = root?.publicId,
                expectedExpenseRowVersion = root?.rowVersion,
            ),
            paymentLabel = root?.merchant,
            paymentAmountCents = root?.amountCents,
            homeCurrency = currency,
        )) }
    }

    fun submit() {
        val state = mutableState.value
        val binding = state.access?.binding ?: return
        val choice = state.choice ?: return
        if (!state.canWrite) return
        mutableState.update { it.copy(saving = true, message = null) }
        viewModelScope.launch {
            val result = repository.enqueue(binding, choice)
            if (mutableState.value.access?.binding != binding) return@launch
            mutableState.update { it.copy(
                saving = false,
                acceptedId = result.getOrNull(),
                choice = if (result.isSuccess) null else choice,
                message = if (result.isSuccess) "提交已保存在本机，等待同步；本期状态以服务器确认为准。"
                    else result.exceptionOrNull()?.message ?: "保存失败，请保留选择后重试。",
            ) }
        }
    }

    fun recover(pending: PendingOccurrencePayment, drop: Boolean) {
        if (pending !in mutableState.value.pending) return
        viewModelScope.launch {
            when (pending.row.status) {
                PendingMutationStatus.Conflict -> if (drop) outbox.resolveConflict(pending.row.id, ConflictResolution.DropMine)
                PendingMutationStatus.Failed -> outbox.resolveFailed(
                    pending.row.id, if (drop) FailedResolution.Drop else FailedResolution.Retry(),
                )
                else -> Unit
            }
            mutableState.update { it.copy(acceptedId = null, choice = null) }
            refresh()
        }
    }

    private fun load(period: String) {
        val state = mutableState.value
        val binding = state.access?.binding ?: return
        val item = state.item ?: return
        val requestEpoch = ++epoch
        mutableState.update { it.copy(loading = true, choice = null, message = null) }
        viewModelScope.launch {
            val result = repository.fetch(binding, item.publicId, period)
            if (requestEpoch != epoch || mutableState.value.access?.binding != binding) return@launch
            mutableState.update { it.copy(
                loading = false, occurrence = result.getOrNull() ?: it.occurrence,
                message = if (result.isFailure) "未能刷新期次。已加载的期次和付款仍可保存提交，联网后会校验版本。" else null,
            ) }
            if (result.isSuccess) ledger.syncConfirmed().onFailure {
                if (requestEpoch == epoch) mutableState.update { it.copy(message = "付款列表未刷新，当前显示本机已保存的流水。") }
            }
        }
    }

    private fun acceptQueue(rows: List<PendingOccurrencePayment>) {
        val previousDone = mutableState.value.queue.filter { it.row.status == PendingMutationStatus.Done }.map { it.row.id }.toSet()
        mutableState.update { it.copy(queue = rows) }
        if (rows.any { it.row.status == PendingMutationStatus.Done && it.row.id !in previousDone }) {
            onChanged()
            if (mutableState.value.item != null) refresh()
        }
    }
}
