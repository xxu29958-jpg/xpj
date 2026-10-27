package com.ticketbox.domain.model

/** Values consumed by the product; wire names and persistence remain at the repository boundary. */
data class ReferenceCreated(
    val kind: String,
    val publicId: String,
    val name: String,
    val rowVersion: Long,
)
