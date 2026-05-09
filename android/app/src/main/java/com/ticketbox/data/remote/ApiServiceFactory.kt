package com.ticketbox.data.remote

interface ApiServiceFactory {
    fun create(baseUrl: String, tokenProvider: () -> String?): ApiService
}
