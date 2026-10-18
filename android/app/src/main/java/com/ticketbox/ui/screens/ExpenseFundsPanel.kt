package com.ticketbox.ui.screens

import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.viewmodel.FundsViewModel

@Composable
internal fun ExpenseFundsPanel(expenseId: Long, refreshExpense: () -> Unit) {
    val repository = LocalFundsRepository.current ?: return
    var open by rememberSaveable(expenseId) { mutableStateOf(false) }
    AppSecondaryButton("付款来源与账户记录") { open = true }
    if (open) {
        val model: FundsViewModel = viewModel(key = "expense-funds:$expenseId", factory = object : ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <T : ViewModel> create(modelClass: Class<T>): T = FundsViewModel(repository, expenseId) as T
        })
        val close = { open = false; refreshExpense() }
        Dialog(onDismissRequest = close, properties = DialogProperties(usePlatformDefaultWidth = false)) {
            Surface { FundsScreen(model, onBack = close, onExpense = { close() }) }
        }
    }
}
