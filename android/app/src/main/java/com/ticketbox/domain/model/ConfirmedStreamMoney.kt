package com.ticketbox.domain.model

import java.util.Locale

/** Sum the visible signed contributions only within each recorded currency. No local FX. */
fun confirmedStreamAmountsByCurrency(items: List<ConfirmedStreamItem>): Map<String?, Long?> =
    items.groupBy { item ->
        val raw = when (item) {
            is ConfirmedStreamItem.ExpenseRow -> item.root.homeCurrencyCode
            is ConfirmedStreamItem.OffsetRow -> item.offset.homeCurrencyCode
        }
        currencyKey(raw)
    }.mapValues { (currency, rows) ->
        if (currency == null || rows.any { it is ConfirmedStreamItem.ExpenseRow && it.root.amountCents == null }) {
            null
        } else {
            runCatching { rows.fold(0L) { total, item -> Math.addExact(total, item.streamAmountCents) } }.getOrNull()
        }
    }

/**
 * Display only: does this stream hold money in more than one currency (any row's home or original
 * code)? Ledger totals name their ISO code only then. A missing code is not a second currency.
 */
fun confirmedStreamRecordsSeveralCurrencies(items: List<ConfirmedStreamItem>): Boolean =
    items.asSequence()
        .flatMap { item ->
            when (item) {
                is ConfirmedStreamItem.ExpenseRow -> sequenceOf(item.root.homeCurrencyCode, item.root.originalCurrencyCodeRaw)
                is ConfirmedStreamItem.OffsetRow -> sequenceOf(item.offset.homeCurrencyCode, item.offset.originalCurrencyCode)
            }
        }
        .mapNotNull(::currencyKey)
        .distinct()
        .take(2)
        .count() > 1

private fun currencyKey(raw: String?): String? = raw?.trim()?.uppercase(Locale.ROOT)?.takeIf { it.isNotEmpty() }
