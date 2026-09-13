package com.ticketbox.data.local

/**
 * ADR-0038 PR-2f outbox status machine.
 *
 * Persisted as the string ``wireValue`` so a future enum addition
 * doesn't need a schema migration; unknown wire values map back to
 * [Unknown] (and the drain worker should refuse to process them
 * rather than crash).
 *
 * Transition diagram:
 * ```
 *                 enqueue
 *                    │
 *                    ▼
 *  ┌───────────► PENDING
 *  │                 │
 *  │             drain start
 *  │                 ▼
 *  │             IN_FLIGHT ──────────────► DONE  (2xx)
 *  │             │      │
 *  │             │      ├──► CONFLICT  (409 state_conflict)
 *  │             │      │      │
 *  │             │      │      ├──► "keep mine" — re-enqueue with
 *  │             │      │      │     fresh token → PENDING
 *  │             │      │      └──► "drop mine" — delete row
 *  │             │      │
 *  │             │      └──► FAILED  (other 4xx/5xx, network)
 *  │             │             │
 *  └─── manual retry ◄──────────┘
 * ```
 *
 * Debt adjustments retain an explicit ABANDONED row after a local stop.
 * It never claims server delivery and is outside runnable/expiry/Done-GC scopes.
 * Other mutation types retain their existing explicit Drop behavior.
 */
enum class PendingMutationStatus(val wireValue: String) {
    Pending("pending"),
    InFlight("in_flight"),
    Conflict("conflict"),
    Failed("failed"),
    Done("done"),
    /** This device stopped sending the retained Debt command; server delivery remains unknown. */
    Abandoned("abandoned"),
    Unknown("unknown");

    companion object {
        fun fromWire(value: String?): PendingMutationStatus {
            if (value == null) return Unknown
            return entries.firstOrNull { it.wireValue == value } ?: Unknown
        }
    }
}
