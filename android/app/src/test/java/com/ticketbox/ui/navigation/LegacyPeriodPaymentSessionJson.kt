package com.ticketbox.ui.navigation

import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import com.ticketbox.data.repository.LegacyPeriodPaymentSession

internal fun leftoverPeriodPaymentSessionsJson(vararg sessions: LegacyPeriodPaymentSession): String =
    requireNotNull(
        Moshi.Builder().build().adapter<List<LegacyPeriodPaymentSession>>(
            Types.newParameterizedType(List::class.java, LegacyPeriodPaymentSession::class.java),
        ).toJson(sessions.toList()),
    )
