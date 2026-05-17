package com.ticketbox.data.remote.dto

/**
 * v0.10 user-scoped UI preferences (theme, etc.).
 * Endpoint: GET / PUT /api/me/ui-preferences. Backend route: app.routes.user_preferences.
 */
data class UserUiPreferencesDto(
    val theme: String? = null,
    val updated_at: String? = null,
)

data class UserUiPreferencesUpdateRequestDto(
    val theme: String? = null,
)
