package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.domain.model.UiText

internal fun Result<String?>.monthReadMessage(): UiText? = when {
    isFailure -> exceptionOrNull()?.toUiText(R.string.financial_month_load_failed)
    getOrNull() == null -> UiText.res(R.string.financial_month_choose)
    else -> null
}
