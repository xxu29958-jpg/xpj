package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.FundsInput
import com.ticketbox.data.repository.FundsInputState
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.UiText
import java.time.YearMonth
import java.util.UUID
import kotlinx.coroutines.launch

fun FundsViewModel.openEnvelopes(month: String = state.value.overview?.valuationDate?.take(7) ?: YearMonth.now().toString()) {
    val binding = state.value.access?.binding ?: return
    if (runCatching { YearMonth.parse(month) }.isFailure) {
        mutable.value = mutable.value.copy(error = UiText.res(R.string.envelopes_invalid_month))
        return
    }
    mutable.value = mutable.value.copy(envelopeMonth = month, envelopes = null, detail = null, error = null,
        envelopeHistory = null, envelopeHistoryMore = false, envelopeHistoryBusy = false)
    viewModelScope.launch { refreshEnvelopes(binding, month) }
}

internal suspend fun FundsViewModel.refreshEnvelopes(binding: LogicalSessionBinding, month: String) {
    mutable.value = mutable.value.copy(loading = true)
    val result = repository.reads.envelopes(binding, month)
    if (state.value.access?.binding != binding || state.value.envelopeMonth != month) return
    result.fold(onSuccess = { read -> mutable.value = mutable.value.copy(envelopes = read.value, loading = false, fromCache = read.fromCache, error = null,
            envelopeHistory = null, envelopeHistoryMore = false) }, onFailure = { error -> mutable.value = mutable.value.copy(loading = false, error = error.toUiText()) })
}

fun FundsViewModel.startEnvelope() {
    val current = state.value
    if (current.task.input != null) { resume(); return }
    val access = current.access?.takeIf { it.canModify } ?: return
    val source = current.envelopes ?: return
    val currency = CurrencyCode.fromStorageKeyOrNull(source.homeCurrencyCode) ?: return
    val value = FundsInput(access.binding, "envelopes", UUID.randomUUID().toString(),
        version = source.rowVersion, currency = source.homeCurrencyCode, envelopeMonth = source.month,
        envelopeAccounts = source.accounts.filter { it.selected }.map { it.publicId },
        envelopeAccountVersions = source.accounts.associate { it.publicId to it.rowVersion },
        envelopeAmounts = source.purposes.associate {
            it.purpose to java.math.BigDecimal.valueOf(it.allocatedMinor, currency.minorUnitDigits).toPlainString()
        })
    mutable.value = mutable.value.copy(task = FundsInputState(value), editing = true, error = null)
    save(value)
}

fun FundsViewModel.loadEnvelopeHistory() {
    val current = state.value
    val binding = current.access?.binding ?: return
    if (current.envelopeHistoryBusy) return
    val before = current.envelopeHistory?.lastOrNull()?.rowVersion
    mutable.value = mutable.value.copy(envelopeHistoryBusy = true)
    viewModelScope.launch {
        val result = repository.reads.envelopeHistory(binding, before)
        if (state.value.access?.binding != binding || state.value.envelopeMonth != current.envelopeMonth) return@launch
        result.fold(onSuccess = { read -> mutable.value = mutable.value.copy(envelopeHistory = (current.envelopeHistory.orEmpty() + read.value).distinctBy { row -> row.rowVersion },
                envelopeHistoryBusy = false, envelopeHistoryMore = read.value.size == 20, fromCache = mutable.value.fromCache || read.fromCache) }, onFailure = { error -> mutable.value = mutable.value.copy(envelopeHistoryBusy = false, error = error.toUiText()) })
    }
}

fun FundsViewModel.useEnvelopePlan() {
    val current = state.value
    val input = current.task.input?.takeIf { it.mode == "envelopes" } ?: return
    val view = current.envelopes?.takeIf { it.month == input.envelopeMonth && it.homeCurrencyCode == input.currency } ?: return
    val currency = CurrencyCode.fromStorageKeyOrNull(input.currency) ?: return
    val planned = view.purposes.mapNotNull { row -> row.plannedMinor?.let {
        row.purpose to java.math.BigDecimal.valueOf(it, currency.minorUnitDigits).toPlainString()
    } }.toMap()
    edit { it.copy(envelopeAmounts = it.envelopeAmounts + planned) }
}
