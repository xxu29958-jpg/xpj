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
 * Terminal states (``DONE`` / ``CONFLICT`` resolved / ``FAILED``
 * dismissed) are garbage-collected by the cleanup path after a
 * grace window so undo / audit can still see them briefly.
 */
enum class PendingMutationStatus(val wireValue: String) {
    Pending("pending"),
    InFlight("in_flight"),
    Conflict("conflict"),
    Failed("failed"),
    Done("done"),
    Unknown("unknown");

    companion object {
        fun fromWire(value: String?): PendingMutationStatus {
            if (value == null) return Unknown
            return entries.firstOrNull { it.wireValue == value } ?: Unknown
        }
    }
}
