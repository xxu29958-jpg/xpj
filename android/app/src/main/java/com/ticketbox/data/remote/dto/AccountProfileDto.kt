package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json

data class AccountProfileDto(
    @param:Json(name = "account_public_id") val accountPublicId: String,
    @param:Json(name = "display_name") val displayName: String,
)

data class AccountProfileRenameDto(
    @param:Json(name = "display_name") val displayName: String,
    @param:Json(name = "expected_name") val expectedName: String,
)
