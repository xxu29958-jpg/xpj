package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.cancel

internal suspend fun cancelMerchantAliasTestViewModels(viewModels: List<MerchantAliasViewModel>) {
    viewModels.forEach { it.viewModelScope.cancel() }
}
