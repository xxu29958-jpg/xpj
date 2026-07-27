package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.BudgetAdviseRequestDto
import com.ticketbox.domain.model.BudgetAdviceResult
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.withContext
import java.util.TimeZone

/** Advice-input sources the backend advisor actually consumes
 *  (backend/app/services/budget_advisor_service/_inputs_builder.py —
 *  confirmed-expense report aggregates, income plans, recurring aggregates;
 *  the monthly budget row is NOT an input). Used as
 *  [BudgetAdviceCallStore.noteAdviceInputSnapshot] source keys. */
const val ADVICE_INPUT_CONFIRMED_EXPENSES = "confirmed_expenses"
const val ADVICE_INPUT_INCOME_PLANS = "income_plans"
const val ADVICE_INPUT_RECURRING_ITEMS = "recurring_items"

/**
 * 218-B4 review chain: in-flight dedupe + process-lifetime last-success cache
 * + freshness tracking for live budget-advice calls.
 *
 * Each live call is quota-counted server-side the moment it starts, so
 * concurrent callers (e.g. a reopened route while the first call is still in
 * flight) attach to ONE in-flight call instead of spending a second
 * reservation. Keys are (logical session binding, month, request timezone,
 * data generation): the binding carries server/account/ledger/generation, so
 * an unbind + re-pair to a different household — even one whose ledger id is
 * also "owner" — can never be served another binding's result; the timezone
 * matches what the request sends (device ZoneId), so a device timezone change
 * can never restore another zone's totals; and the generation is bumped by
 * [invalidate], so a pre-write in-flight call can neither be re-attached nor
 * repopulate the cache.
 *
 * Guarded by a plain monitor ([lock]) because every critical section is
 * non-suspending map I/O — that keeps [invalidate] callable from non-suspend
 * refresh callbacks. Everything is in-memory only — process-lifetime, never
 * persisted (the advice round-trip persists nothing on device).
 */
internal class BudgetAdviceCallStore(
    private val ledgerRequestGuard: LedgerRequestGuard,
    private val errorHandler: NetworkErrorHandler,
) {
    private val lock = Any()
    private val inFlight = mutableMapOf<AdviceRequestKey, CompletableDeferred<Result<BudgetAdviceResult>>>()
    private val lastSuccess = mutableMapOf<AdviceRequestKey, BudgetAdviceResult>()
    private var dataGeneration = 0

    private val _invalidations = MutableStateFlow(0)

    /** The current advice data generation as an observable flow: the value
     *  bumps on every [invalidate]. Lets a LIVE advice ViewModel learn that
     *  the result it is displaying was produced from pre-write inputs (the
     *  cache it would restore from is already cleared — this is for the
     *  still-visible state). */
    val invalidations: StateFlow<Int> = _invalidations.asStateFlow()

    /** Last-delivered freshness stamp per advice-input source, same lock and
     *  lifetime as the maps above. See [noteAdviceInputSnapshot]. */
    private val inputStamps = mutableMapOf<String, String>()

    /** Attaches to the in-flight call for this (binding, month) or starts it.
     *  One key capture per request: the same timezone value keys the maps and
     *  rides the wire (BudgetAdviseRequestDto.timezone); the same data
     *  generation decides attach eligibility, atomically with the dedupe. */
    suspend fun attachOrRequest(
        binding: LogicalSessionBinding,
        month: String,
    ): Result<BudgetAdviceResult> {
        val (key, deferred, isOwner) = synchronized(lock) {
            val key = AdviceRequestKey(
                binding = binding,
                month = month,
                timezone = currentTimezoneId(),
                dataGeneration = dataGeneration,
            )
            val existing = inFlight[key]
            if (existing != null) {
                Triple(key, existing, false)
            } else {
                val created = CompletableDeferred<Result<BudgetAdviceResult>>()
                inFlight[key] = created
                Triple(key, created, true)
            }
        }
        if (!isOwner) return deferred.await()
        return runCall(key, deferred, month)
    }

    private suspend fun runCall(
        key: AdviceRequestKey,
        deferred: CompletableDeferred<Result<BudgetAdviceResult>>,
        month: String,
    ): Result<BudgetAdviceResult> = withContext(NonCancellable) {
        // NonCancellable: the page-scoped VM dies on route exit (viewModelScope
        // cancelled) while the backend may already have reserved the call.
        // Running to completion lets attached callers and the last-success
        // cache still observe the result instead of forcing a second call.
        val result = errorHandler.safeCall {
            ledgerRequestGuard.bindExact(key.binding).call { api ->
                api.budgetAdvise(
                    BudgetAdviseRequestDto(
                        month = month,
                        timezone = key.timezone,
                    ),
                ).toDomain()
            }
        }
        synchronized(lock) {
            // Only a real advice payload is cached: a null-advice result (e.g.
            // provider_empty) must never be restored, or a later operator-side
            // fix would stay invisible behind the cached terminal state. And a
            // call that started BEFORE an advice-input write (stale generation)
            // may still deliver to its attached callers, but must not
            // repopulate the cache with pre-write advice.
            result.getOrNull()
                ?.takeIf { it.advice != null && key.dataGeneration == dataGeneration }
                ?.let { lastSuccess[key] = it }
            inFlight.remove(key)
        }
        deferred.complete(result)
        result
    }

    /** Process-lifetime last-successful advice for [month] under the CURRENT
     *  logical session binding, request timezone and data generation, written
     *  only on a success that carries an actual advice payload — failures and
     *  null-advice results leave the cache absent. Nothing is persisted; an
     *  app restart simply starts cold. The binding is part of the lookup key,
     *  so a re-paired household never sees a previous binding's entry. */
    fun cached(binding: LogicalSessionBinding, month: String): BudgetAdviceResult? =
        synchronized(lock) {
            lastSuccess[
                AdviceRequestKey(
                    binding = binding,
                    month = month,
                    timezone = currentTimezoneId(),
                    dataGeneration = dataGeneration,
                ),
            ]
        }

    fun invalidate() {
        synchronized(lock) {
            // Bump the generation so pre-write in-flight calls can neither be
            // re-attached nor write the cache on completion, then drop the now
            // unreachable entries. Attached collectors keep their deferred and
            // still observe their own (stale) result — that delivery is fine.
            dataGeneration += 1
            lastSuccess.clear()
            inFlight.clear()
            _invalidations.value = dataGeneration
        }
    }

    /** Freshness sink for server-delivered advice inputs (the refresh-side
     *  counterpart of [invalidate]'s local-write invalidation). The
     *  repositories whose fetches deliver data the advisor consumes call this
     *  with a cheap stable [stamp] of the delivered snapshot (count + max
     *  row_version/updated_at). A CHANGED stamp — including the first sighting
     *  in this process, which cannot prove the cache was built from the same
     *  server state — invalidates the advice cache; an IDENTICAL stamp (a
     *  no-op refresh) preserves it, so reopening the advice page after an
     *  unchanged refresh still costs zero live calls. */
    fun noteAdviceInputSnapshot(source: String, stamp: String) {
        val changed = synchronized(lock) {
            val changed = inputStamps[source] != stamp
            if (changed) {
                inputStamps[source] = stamp
            }
            changed
        }
        if (changed) {
            invalidate()
        }
    }

    private fun currentTimezoneId(): String = TimeZone.getDefault().id
}

private data class AdviceRequestKey(
    val binding: LogicalSessionBinding,
    val month: String,
    val timezone: String,
    val dataGeneration: Int,
)
