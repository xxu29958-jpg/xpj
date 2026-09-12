package com.ticketbox.data.repository

import kotlinx.coroutines.CancellationException

/** A local projection failure cannot reverse a server-accepted Expense command. */
internal suspend fun publishAcceptedExpense(
    expenseId: Long,
    rowVersion: Long,
    publish: suspend () -> Unit,
): DispatchResult.Success = try {
    publish()
    DispatchResult.Success(newRowVersion = rowVersion)
} catch (cancelled: CancellationException) {
    throw cancelled
} catch (_: Exception) {
    DispatchResult.Success(newRowVersion = rowVersion, cacheRefreshVersion = rowVersion,
        receiptJson = expenseAcceptanceReceiptJson(expenseId))
}

/** Notification is best effort after adoption; cancellation keeps its original meaning. */
internal fun notifyConfirmedExpenseWrite(ledgerId: String, notify: (String) -> Unit) {
    try {
        notify(ledgerId)
    } catch (cancelled: CancellationException) {
        throw cancelled
    } catch (_: Exception) {
        // An adopted snapshot remains valid when its notification cannot be scheduled.
    }
}
