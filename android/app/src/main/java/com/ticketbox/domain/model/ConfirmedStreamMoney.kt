package com.ticketbox.domain.model

import java.util.Locale

/** Sum the visible signed contributions only within each recorded currency. No local FX. */
fun confirmedStreamAmountsByCurrency(items: List<ConfirmedStreamItem>): Map<String?, Long?> =
    items.groupBy { item ->
        val raw = when (item) {
            is ConfirmedStreamItem.ExpenseRow -> item.root.homeCurrencyCode
            is ConfirmedStreamItem.OffsetRow -> item.offset.homeCurrencyCode
        }
        raw?.trim()?.uppercase(Locale.ROOT)?.takeIf { it.isNotEmpty() }
    }.mapValues { (currency, rows) ->
        if (currency == null || rows.any { it is ConfirmedStreamItem.ExpenseRow && it.root.amountCents == null }) {
            null
        } else {
            runCatching { rows.fold(0L) { total, item -> Math.addExact(total, item.streamAmountCents) } }.getOrNull()
        }
    }
