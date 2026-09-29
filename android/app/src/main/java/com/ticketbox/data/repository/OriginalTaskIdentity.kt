package com.ticketbox.data.repository

/** Optional original task scope; credential renewal does not change the data owner. */
internal fun LogicalSessionBinding?.admitsTaskBinding(current: LogicalSessionBinding?): Boolean =
    this == null || current != null && serverUrl == current.serverUrl && ownerKey == current.ownerKey && ledgerId == current.ledgerId
