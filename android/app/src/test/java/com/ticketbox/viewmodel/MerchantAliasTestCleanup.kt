package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.job

internal suspend fun cancelMerchantAliasTestViewModels(viewModels: List<MerchantAliasViewModel>) {
    // Repository safeCall uses real IO. Resetting Main is safe only after
    // every child has completed, not merely after cancellation was requested.
    viewModels.forEach { it.viewModelScope.coroutineContext.job.cancelAndJoin() }
}
