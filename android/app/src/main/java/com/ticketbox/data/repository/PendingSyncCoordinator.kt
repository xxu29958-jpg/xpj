package com.ticketbox.data.repository

import com.ticketbox.domain.model.Expense
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

/**
 * Coalesces overlapping Pending refreshes for one ledger into one canonical
 * trailing sync. The first caller owns execution; later callers mark the run
 * dirty and await the same final result, so a response captured before OCR can
 * never finish after and overwrite the terminal snapshot in Room.
 */
internal class PendingSyncCoordinator {
    private data class ActiveRun(
        var dirty: Boolean,
        var operation: suspend () -> List<Expense>,
        val completion: CompletableDeferred<Result<List<Expense>>>,
    )

    private val guard = Mutex()
    private val activeByLedger = mutableMapOf<String, ActiveRun>()

    suspend fun sync(
        ledgerId: String,
        operation: suspend () -> List<Expense>,
    ): List<Expense> {
        lateinit var run: ActiveRun
        var ownsRun = false
        guard.withLock {
            val active = activeByLedger[ledgerId]
            if (active == null) {
                run = ActiveRun(
                    dirty = false,
                    operation = operation,
                    completion = CompletableDeferred(),
                )
                activeByLedger[ledgerId] = run
                ownsRun = true
            } else {
                active.dirty = true
                active.operation = operation
                run = active
            }
        }

        if (!ownsRun) {
            return try {
                run.completion.await().getOrThrow()
            } catch (cancelledOwner: CancellationException) {
                // A NavBackStackEntry/ViewModel may be cleared while a newer
                // caller is already attached to its canonical refresh. The
                // attached caller is still active, so it must take ownership
                // instead of inheriting the old owner's cancellation.
                currentCoroutineContext().ensureActive()
                sync(ledgerId, operation)
            }
        }

        try {
            while (true) {
                val currentOperation = guard.withLock {
                    run.dirty = false
                    run.operation
                }
                val result = try {
                    Result.success(currentOperation())
                } catch (cancelled: CancellationException) {
                    throw cancelled
                } catch (error: Throwable) {
                    Result.failure(error)
                }
                val mustRunAgain = guard.withLock {
                    if (run.dirty) {
                        true
                    } else {
                        activeByLedger.remove(ledgerId, run)
                        run.completion.complete(result)
                        false
                    }
                }
                if (!mustRunAgain) return result.getOrThrow()
            }
        } catch (error: Throwable) {
            releaseOwnerAfterFailure(ledgerId, run, error)
            throw error
        }
    }

    private suspend fun releaseOwnerAfterFailure(
        ledgerId: String,
        run: ActiveRun,
        error: Throwable,
    ) {
        withContext(NonCancellable) {
            guard.withLock {
                if (activeByLedger.remove(ledgerId, run)) {
                    run.completion.complete(Result.failure(error))
                }
            }
        }
    }
}
