package com.ticketbox.domain.model

/** Values consumed by the product; wire names and persistence remain at the repository boundary. */
data class EnvelopeAccount(
    val name: String,
    val publicId: String,
    val currencyCode: String,
    val balanceMinor: Long?,
    val rowVersion: Long,
    val selected: Boolean, val canSelect: Boolean
)

data class EnvelopeMonth(
    val month: String,
    val reservedMinor: Long?
)

data class EnvelopePurpose(
    val purpose: String, val label: String, val funded: Boolean,
    val plannedMinor: Long?,
    val allocatedMinor: Long,
    val spentMinor: Long?,
    val unpaidCreditMinor: Long?,
    val unlinkedMinor: Long?,
    val availableMinor: Long?,
    val reservedMinor: Long?
)

data class EnvelopeRevision(
    val rowVersion: Long, val month: String, val reason: String,
    val recordedAt: String,
    val allocationSnapshot: EnvelopeSnapshot
)

data class EnvelopeSnapshot(
    val homeCurrencyCode: String,
    val accountPublicIds: List<String>,
    val allocations: Map<String, Long>
)

data class Envelopes(
    val ledgerId: String, val month: String,
    val homeCurrencyCode: String,
    val rowVersion: Long,
    val readAt: String,
    val valuationDate: String,
    val cashMinor: Long?,
    val reservedMinor: Long?,
    val unassignedMinor: Long?,
    val accounts: List<EnvelopeAccount>, val purposes: List<EnvelopePurpose>,
    val months: List<EnvelopeMonth>, val notices: List<String>,
)
