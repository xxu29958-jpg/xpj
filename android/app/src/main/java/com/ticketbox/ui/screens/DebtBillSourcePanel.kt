package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Column
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.data.remote.dto.DebtBillCaptureDto
import com.ticketbox.data.repository.DebtBillActions
import com.ticketbox.viewmodel.DebtDetailUiState
import kotlinx.coroutines.launch

/** The source actor remains private even when the linked Debt is visible to other participants. */
@Composable
internal fun DebtBillSourcePanel(state: DebtDetailUiState, sources: DebtBillActions) {
    val binding = state.binding ?: return
    val debt = state.debt ?: return
    androidx.compose.runtime.key(binding, debt.publicId) {
        var rows by remember { mutableStateOf<List<DebtBillCaptureDto>>(emptyList()) }
        var error by remember { mutableStateOf(false) }
        var refresh by remember { mutableStateOf(0) }
        var preview by remember { mutableStateOf<ByteArray?>(null) }
        val scope = rememberCoroutineScope()
        LaunchedEffect(refresh, debt.rowVersion) {
            val result = sources.forDebt(binding, debt.publicId)
            rows = result.getOrDefault(emptyList())
            error = result.isFailure
        }
        Column {
            if (error) DebtBillOriginalRow(listOf(stringResource(R.string.debt_bill_retry_original)), readable = false,
                showDivider = rows.isNotEmpty(), onClick = { refresh++ })
            rows.forEachIndexed { index, source ->
                val readable = source.originalState == "verified"
                DebtBillOriginalRow(
                    lines = if (readable) listOf(source.fileName) else listOf(source.fileName, stringResource(
                        if (source.originalState == "cleaned") R.string.debt_bill_original_cleaned
                        else R.string.debt_bill_original_unavailable)),
                    readable = readable,
                    showDivider = index < rows.lastIndex,
                    onClick = if (readable) { { scope.launch {
                        val result = sources.original(binding, source.publicId)
                        preview = result.getOrNull()
                        error = result.isFailure
                    } } } else null,
                )
            }
        }
        preview?.let { bytes -> DebtBillOriginalDialog(bytes) { preview = null } }
    }
}
