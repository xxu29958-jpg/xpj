package com.ticketbox.ui.navigation

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.ticketbox.R
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.ManualEntryTemplate
import com.ticketbox.data.repository.ManualEntryTemplateStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

internal class ManualTemplateController(
    private val store: ManualEntryTemplateStore,
    private val binding: LogicalSessionBinding,
    private val currentBinding: () -> LogicalSessionBinding?,
    private val scope: CoroutineScope,
) {
    var entries by mutableStateOf<List<ManualEntryTemplate>?>(null)
        private set
    var error by mutableStateOf<Int?>(null)
        private set
    var busy by mutableStateOf(false)
        private set

    suspend fun reload() {
        runCatching { withContext(Dispatchers.IO) { store.read() } }
            .onSuccess { entries = it; error = null }
            .onFailure { error = R.string.widget_template_read_failed }
    }

    fun change(block: () -> Unit, onComplete: () -> Unit) {
        if (currentBinding() != binding || busy) return
        scope.launch {
            busy = true
            runCatching { withContext(Dispatchers.IO) { block(); store.read() } }
                .onSuccess { entries = it; error = null; onComplete() }
                .onFailure { error = R.string.widget_template_write_failed }
            busy = false
        }
    }
}
