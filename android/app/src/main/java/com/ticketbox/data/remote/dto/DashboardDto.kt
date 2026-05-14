package com.ticketbox.data.remote.dto

data class DashboardCardDto(
    val key: String,
    val title: String,
    val visible: Boolean,
    val position: Int,
)

data class DashboardCardsResponseDto(
    val surface: String,
    val items: List<DashboardCardDto>,
)

data class DashboardCardUpdateRequestDto(
    val key: String,
    val visible: Boolean,
    val position: Int,
)

data class DashboardCardsUpdateRequestDto(
    val cards: List<DashboardCardUpdateRequestDto>,
)
