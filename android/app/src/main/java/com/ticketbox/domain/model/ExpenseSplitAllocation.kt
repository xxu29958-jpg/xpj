package com.ticketbox.domain.model

/**
 * Largest-remainder even split of [totalCents] across [count] members, by
 * position. ``base = totalCents / count`` (floor) goes to everyone; the first
 * ``r = totalCents % count`` members each get one extra cent. Deterministic by
 * index (NOT random), so ¥100.00/3 → 33.34 / 33.33 / 33.33. Returns an empty
 * list for ``count <= 0`` and treats a negative total as zero (the editor never
 * feeds a negative parent amount).
 */
fun evenSplitCents(totalCents: Long, count: Int): List<Long> {
    if (count <= 0) return emptyList()
    val safeTotal = totalCents.coerceAtLeast(0L)
    val base = safeTotal / count
    val remainder = (safeTotal % count).toInt()
    return List(count) { index -> if (index < remainder) base + 1 else base }
}

/**
 * [evenSplitCents] of [parentCents] across [activeCount] active members AFTER
 * reserving [fixedDisabledCents] for disabled members already on the split (whose
 * shares the user can't edit). The active shares + the fixed disabled shares then
 * sum back to the parent total, so 均分 actually drives 差额 to zero. An
 * over-reserved fixed total (> parent) clamps the distributable amount to zero.
 */
fun evenSplitActiveCents(parentCents: Long, fixedDisabledCents: Long, activeCount: Int): List<Long> =
    evenSplitCents((parentCents - fixedDisabledCents).coerceAtLeast(0L), activeCount)
